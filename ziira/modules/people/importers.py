"""Importing employees from a file: People's `imports.importer`. Only the person and where they work are imported; pay
terms and bank details have their own permission and are set in People > Pay afterwards."""

from uuid import UUID

from sqlalchemy import text

from ziira.modules.imports.public import ImportColumn, Importer, ImportRow, attempt
from ziira.modules.people.domain import identity
from ziira.modules.people.permissions import EMPLOYEES_MANAGE
from ziira.modules.people.services.employees import RESIDENCY, create_employee
from ziira.sdk import Session, ValidationFailed, company_setting


class EmployeeImporter(Importer):
    kind = "employees"
    title = "Employees"
    description = ("Your staff list: one row per employee. Pay terms and bank details are not imported (they have "
                   "their own permission); set them in People afterwards.")
    permission = EMPLOYEES_MANAGE
    columns = (
        ImportColumn("full_name", True, "The employee's full name.", "Wanjiru Kamau", aliases=("name", "employee")),
        ImportColumn("hire_date", True, "Date they started (YYYY-MM-DD unless you choose another date format).",
                     "2023-02-01", aliases=("start date", "date hired", "joined")),
        ImportColumn("employee_no", False, "Your staff number. Left out, Ziira numbers them.", "E-014",
                     aliases=("staff number", "staff no", "payroll number", "employee number")),
        ImportColumn("branch", False, "Code of the branch they work at.", "HQ", aliases=("branch code", "location")),
        ImportColumn("department", False, "Name of their department (must exist in Ziira).", "Sales"),
        ImportColumn("national_id", False, "ID or passport number.", "12345678", aliases=("id number", "passport")),
        ImportColumn("tax_id", False, "Personal tax number.", "A001234567B", aliases=("tax number", "pin")),
        ImportColumn("phone", False, "Phone number.", "0733000222", aliases=("mobile", "telephone")),
        ImportColumn("email", False, "Email address.", "wanjiru@example.com"),
        ImportColumn("residency", False, "resident (default) or non_resident.", "resident"),
        ImportColumn("is_director", False, "yes if they are a director.", "no", aliases=("director",)),
    )
    reversal_note = "Employees cannot be deleted. End their employment in People instead."

    def key(self, row: ImportRow) -> str | None:
        return row.text("employee_no").upper() or None

    def _read(self, session: Session, company_id: UUID, row: ImportRow, errors: list[str]) -> dict[str, object]:
        name = " ".join(row.text("full_name").split())
        if not name or len(name) > 200:
            errors.append("full_name: a name of up to 200 characters is needed")
        hired = row.day("hire_date", errors)
        if hired is None and not row.text("hire_date"):
            errors.append("hire_date: the start date is needed")
        number = row.text("employee_no").upper()
        if len(number) > 30:
            errors.append("employee_no: at most 30 characters")
        branch_id = department_id = None
        if row.text("branch"):
            found = session.execute(text("select id from kernel.branch where company_id = :c and code = :b"),
                                    {"c": str(company_id), "b": row.text("branch").upper()}).first()
            branch_id = found.id if found else None
            if found is None:
                errors.append(f"branch: no branch with code {row.text('branch').upper()}")
        if row.text("department"):
            found = session.execute(text(
                "select id from people.department where company_id = :c and lower(name) = lower(:n)"),
                {"c": str(company_id), "n": row.text("department")}).first()
            department_id = found.id if found else None
            if found is None:
                errors.append(f"department: '{row.text('department')}' does not exist. Add it in People first.")
        residency = (row.text("residency") or "resident").lower().replace(" ", "_").replace("-", "_")
        if residency not in RESIDENCY:
            errors.append("residency: write resident or non_resident")
        calling_code = str(company_setting(session, company_id, "phone_country_code"))
        attempt(errors, lambda: identity.national_id(row.text("national_id")))
        attempt(errors, lambda: identity.tax_id(row.text("tax_id")))
        attempt(errors, lambda: identity.phone(row.text("phone"), calling_code))
        attempt(errors, lambda: identity.email(row.text("email")))
        return {"name": name, "hired": hired, "number": number, "branch_id": branch_id,
                "department_id": department_id, "residency": residency,
                "director": row.yes_no("is_director", errors) or False}

    def validate_row(self, session: Session, company_id: UUID, row: ImportRow) -> list[str]:
        errors: list[str] = []
        self._read(session, company_id, row, errors)
        return errors

    def existing(self, session: Session, company_id: UUID, row: ImportRow) -> str | None:
        number = row.text("employee_no").upper()
        if number:
            found = session.execute(text("select 1 from people.employee where company_id = :c and employee_no = :n"),
                                    {"c": str(company_id), "n": number}).first()
            return f"Employee {number} already exists" if found else None
        errors: list[str] = []
        hired = row.day("hire_date", errors)
        found = session.execute(text(
            "select 1 from people.employee where company_id = :c and lower(full_name) = lower(:n) "
            "and hire_date = :d"), {"c": str(company_id), "n": " ".join(row.text("full_name").split()),
                                    "d": hired}).first() if hired else None
        return f"{row.text('full_name')} (started {hired}) already exists" if found else None

    def import_row(self, session: Session, company_id: UUID, row: ImportRow, local_id: UUID) -> UUID:
        errors: list[str] = []
        read = self._read(session, company_id, row, errors)
        if errors:
            raise ValidationFailed("; ".join(errors))
        employee = create_employee(
            session, company_id=company_id, full_name=str(read["name"]), hire_date=read["hired"],  # type: ignore[arg-type]
            branch_id=read["branch_id"], department_id=read["department_id"],  # type: ignore[arg-type]
            employee_no=str(read["number"]) or None, national_id=row.text("national_id") or None,
            tax_id=row.text("tax_id") or None, phone=row.text("phone") or None, email=row.text("email") or None,
            residency=str(read["residency"]), is_director=bool(read["director"]))
        return employee.id

