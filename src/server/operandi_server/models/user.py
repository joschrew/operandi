from pydantic import BaseModel, Field


class UserAction(BaseModel):
    account_type: str = Field(
        ...,  # the field is required, no default set
        description="The type of this user"
    )
    action: str = Field(
        default="Description of the user action",
        description="Description of the user action"
    )
    email: str = Field(
        ...,  # the field is required, no default set
        description="Email linked to this User"
    )

    class Config:
        allow_population_by_field_name = True

    @staticmethod
    def create(account_type: str, action: str, email: str):
        if not action:
            action = "User Action"
        return UserAction(account_type=account_type, action=action, email=email)
