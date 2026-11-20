from pydantic import BaseModel, Field


class RetestBatchInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    source: str = Field(default='retest.json', max_length=200)
    records: list[dict] = Field(min_length=5, max_length=5000)


class RetestTrialInput(BaseModel):
    origin_job_id: int
    retest_batch_id: int


class RetestIssueInput(BaseModel):
    origin_job_id: int
    retest_batch_id: int
    request_key: str = Field(min_length=8, max_length=80)
