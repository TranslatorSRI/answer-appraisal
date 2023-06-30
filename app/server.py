import logging
import traceback
import os

from fastapi import Body, BackgroundTasks
from fastapi.responses import JSONResponse
import httpx
from starlette.middleware.cors import CORSMiddleware
from uuid import uuid4

from reasoner_pydantic import (
    AsyncQuery,
    AsyncQueryResponse,
    Response,
    Query
)

from .logger import setup_logger, get_logger
from .trapi import TRAPI
from .ordering_components import get_ordering_components


setup_logger()
LOGGER = logging.getLogger(__name__)

openapi_args = dict(
    title="Answer Appraiser",
    version="0.1.0",
    terms_of_service="",
    translator_component="Utility",
    translator_teams=["Standards Reference Implementation Team"],
    infores="infores:answer-appraiser",
    contact={
        "name": "Abrar Mesbah",
        "email": "amesbah@covar.com",
        "x-id": "uhbrar",
        "x-role": "responsible developer",
    },
)

OPENAPI_SERVER_URL = os.getenv("OPENAPI_SERVER_URL")
OPENAPI_SERVER_MATURITY = os.getenv("OPENAPI_SERVER_MATURITY", "development")
OPENAPI_SERVER_LOCATION = os.getenv("OPENAPI_SERVER_LOCATION", "RENCI")
TRAPI_VERSION = os.getenv("TRAPI_VERSION", "1.4.0")

if OPENAPI_SERVER_URL:
    openapi_args["servers"] = [
        {
            "url": OPENAPI_SERVER_URL,
            "x-maturity": OPENAPI_SERVER_MATURITY,
            "x-location": OPENAPI_SERVER_LOCATION,
        },
    ]

openapi_args["trapi"] = TRAPI_VERSION

APP = TRAPI(**openapi_args)

APP.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

EXAMPLE = {
  "message": {
      "query_graph": {
          "nodes": {
              "n0": {"ids": ["MESH:D008687"]},
              "n1": {"categories": ["biolink:Disease"]}
          },
          "edges": {
              "n0n1": {
                  "subject": "n0",
                  "object": "n1",
                  "predicates": ["biolink:treats"]
              }
          }
      },
      "knowledge_graph": {
          "nodes": {
              "MESH:D008687": {
                  "categories": ["biolink:SmallMolecule"],
                  "name": "Metformin"
              },
              "MONDO:0005148": {
                  "categories": [
                      "biolink:Disease"
                  ],
                  "name": "type 2 diabetes mellitus"
              }
          },
          "edges": {
              "n0n1": {
                  "subject": "MESH:D008687",
                  "object": "MONDO:0005148",
                  "predicate": "biolink:treats",
                  "sources": [
                      {
                          "resource_id": "infores:kp0",
                          "resource_role": "primary_knowledge_source"
                      }
                  ]
              }
          }
      },
      "results": [
          {
              "node_bindings": {
                  "n0": [
                      {
                          "id": "MESH:D008687"
                      }
                  ],
                  "n1": [
                      {
                          "id": "MONDO:0005148"
                      }
                  ]
              },
              "analyses": [
                  {
                      "resource_id": "kp0",
                      "edge_bindings": {
                          "n0n1": [
                              {
                                  "id": "n0n1"
                              }
                          ]
                      }
                  }
              ]
          }
      ]
  }
}

ASYNC_EXAMPLE = {
    "callback": "http://test",
    **EXAMPLE,
}


async def async_appraise(message, callback, logger: logging.Logger):
    try:
        get_ordering_components(message, logger)
    except Exception:
        logger.error(f"Something went wrong while appraising: {traceback.format_exc()}")
    try:    
        logger.info(f"Posting to callback {callback}")
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout=600.0)) as client:
            res = await client.post(callback, json=message)
            logger.info(f"Posted to {callback} with code {res.status_code}")
    except Exception as e:
        logger.error(f"Unable to post to callback {callback}.")

@APP.post("/async_get_appraisal", response_model=AsyncQueryResponse)
async def get_appraisal(
    background_tasks: BackgroundTasks,
    query: AsyncQuery = Body(..., example=ASYNC_EXAMPLE)
):
    """Appraise Answers"""
    qid = str(uuid4())[:8]
    query_dict = query.dict()
    log_level = query_dict.get("log_level") or "WARNING"
    logger = get_logger(qid, log_level)
    message = query_dict["message"]
    if not message.get("results"):
        logger.warning("No results given.")
        return JSONResponse(content={"status": "Rejected",
                                     "description": "No Results.",
                                     "job_id": qid}, status_code=400)
    callback = query_dict["callback"]
    background_tasks.add_task(async_appraise, message, callback, logger)
    return JSONResponse(content={"status": "Accepted",
                                 "description": f"Appraising answers. Will send response to {callback}",
                                 "job_id": qid}, status_code=200)

@APP.post("/get_appraisal", response_model=Response)
async def sync_get_appraisal(
    query: Query = Body(..., example=EXAMPLE)
):
    qid = str(uuid4())[:8]
    query_dict = query.dict()
    log_level = query_dict.get("log_level") or "WARNING"
    logger = get_logger(qid, log_level)
    message = query_dict["message"]
    if not message.get("results"):
        return JSONResponse(content={"status": "Rejected",
                                     "description": "No Results.",
                                     "job_id": qid}, status_code=400)
    try:
        get_ordering_components(message, logger)
    except Exception:
        logger.error(f"Something went wrong while appraising: {traceback.format_exc()}")
    return Response(message=message)
