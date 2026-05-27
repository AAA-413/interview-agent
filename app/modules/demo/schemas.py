from pydantic import BaseModel


class DemoSeedResponse(BaseModel):
    resume_id: int
    interview_session_id: str
    resume_path: str
    interview_report_path: str
    message: str
