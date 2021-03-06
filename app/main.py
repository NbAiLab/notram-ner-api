import json
import os
from typing import List
from urllib.request import urlopen
from uuid import uuid4

from celery.result import AsyncResult
from fastapi import FastAPI, APIRouter
from fastapi.responses import RedirectResponse

from app.schemas import NerTextRequest, NerUrnRequest, NerUrlRequest, NerResponse
from app.util import USE_QUEUE, URN_BASE_PATH, ROOT_PATH, VERSION
from app.util import urn_to_path, get_text
from .tasks import app as task_app
from .tasks import run_model_task, model

TITLE = "notram-ner-api"
DESCRIPTION = """
API for communication with Named Entity Recognition (NER) model based on NoTraM (Norwegian Transformer Model).
"""

api_args = dict(
    description=DESCRIPTION,
    version=f"v{VERSION}",
    license_info={
        "name": "Apache 2.0",
        "url": "https://www.apache.org/licenses/LICENSE-2.0.html",
    },
)
api = FastAPI(
    title=TITLE,
    **api_args
)


@api.get("/")
async def home():
    return RedirectResponse(ROOT_PATH + api.docs_url)


@api.get("/groups", response_model=List[str])
async def groups():
    """
    Get available entity groups.
    """
    entity_groups = []
    for label in model.model.config.id2label.values():
        s = label.split("-")
        if s[0] != "I":
            entity_groups.append(s[-1])
    return entity_groups


@api.post("/text")
async def named_entities_from_text(body: NerTextRequest) -> NerResponse:
    """
    Get named entities for a specific text.
    """
    method = run_model_task.delay if USE_QUEUE else run_model_task

    res = method(
        text=body.text,
        include_entities=body.include_entities,
        do_group_entities=body.group_entities
    )

    if USE_QUEUE:
        if body.wait:
            res.get()

        return {"status": res.status, "uuid": res.id, "result": res.result}  # noqa

    return {"status": "SUCCESS", "uuid": str(uuid4()), "result": res}  # noqa


@api.post("/website")
async def named_entities_from_website(body: NerUrlRequest):
    html = urlopen(body.url)
    text = get_text(html)

    return await named_entities_from_text(
        NerTextRequest(
            text=text,
            include_entities=body.include_entities,
            group_entities=body.group_entities,
            wait=body.wait
        )
    )


if URN_BASE_PATH is not None:
    @api.post("/urn")

    async def named_entities_from_urn(body: NerUrnRequest):
        """
        Get named entities for a specific URN.
        """
        path = os.path.join(URN_BASE_PATH, urn_to_path(body.urn))
        with open(path) as file:
            jsonl = [json.loads(line) for line in file]

        jsonl = jsonl[0]  # Assuming only one record for now
        all_text = "\n".join([paragraph["text"] for paragraph in jsonl["paragraphs"]])
        # TODO keep track of index?

        return await named_entities_from_text(
            NerTextRequest(
                text=all_text,
                include_entities=body.include_entities,
                group_entities=body.group_entities,
                wait=body.wait
            )
        )

if USE_QUEUE:
    @api.get("/task/{uuid}")

    async def task_result(uuid: str):
        res = AsyncResult(uuid, app=task_app)
        # TODO handle invalid uuid? Status is PENDING for invalid tasks also
        return {"status": res.status, "uuid": res.id, "result": res.result}

app = FastAPI(
    title=TITLE,
    **api_args
)

@app.get("/")
async def home():
    return RedirectResponse(ROOT_PATH + api.docs_url)

app.mount(ROOT_PATH, api)
