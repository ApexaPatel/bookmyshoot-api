from fastapi import APIRouter, Depends, HTTPException, status

from app.crud.organization import CRUDOrganization, get_organization_crud
from app.models.organization import OrganizationCreate, OrganizationResponse

router = APIRouter()


@router.post("", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    data: OrganizationCreate,
    org_crud: CRUDOrganization = Depends(get_organization_crud),
):
    """Create a new organization. Returns the created organization with _id."""
    if not data.name or not data.name.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization name is required",
        )
    org = await org_crud.create({
        "name": data.name.strip(),
        "location": data.location and data.location.strip() or None,
        "contact_number": data.contact_number and data.contact_number.strip() or None,
    })
    return OrganizationResponse(**org.dict(by_alias=False))
