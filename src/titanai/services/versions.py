import aiosqlite

from titanai.db.repositories import book_versions as version_repo
from titanai.db.repositories import books as book_repo


async def compare_and_version(
    db: aiosqlite.Connection,
    tenant_id: str,
    book_id: str,
    new_title: str,
    new_authors: list[str],
    new_first_publish_year: int | None,
    new_subjects: list[str] | None,
    new_cover_image_url: str | None,
) -> bool:
    book = await book_repo.get_book(db, tenant_id, book_id)
    if book is None:
        return False

    diff: dict[str, dict] = {}
    has_regression = False
    regression_fields: list[str] = []

    # Compare fields
    fields = [
        ("title", book.title, new_title),
        ("authors", book.authors, new_authors),
        ("first_publish_year", book.first_publish_year, new_first_publish_year),
        ("subjects", book.subjects, new_subjects),
        ("cover_image_url", book.cover_image_url, new_cover_image_url),
    ]

    # Values to actually store on the book (preserving regressed fields)
    final_title = new_title
    final_authors = new_authors
    final_first_publish_year = new_first_publish_year
    final_subjects = new_subjects
    final_cover_image_url = new_cover_image_url

    for field_name, old_val, new_val in fields:
        if old_val != new_val:
            diff[field_name] = {"old": old_val, "new": new_val}

            # Regression detection: field was non-null and is now null
            if old_val is not None and new_val is None:
                has_regression = True
                regression_fields.append(field_name)
                # Preserve old value for regressed fields
                if field_name == "title":
                    final_title = old_val
                elif field_name == "authors":
                    final_authors = old_val
                elif field_name == "first_publish_year":
                    final_first_publish_year = old_val
                elif field_name == "subjects":
                    final_subjects = old_val
                elif field_name == "cover_image_url":
                    final_cover_image_url = old_val

    if not diff:
        return False

    new_version_number = book.current_version + 1

    # Create version record
    await version_repo.create_version(
        db, book_id,
        version_number=new_version_number,
        title=new_title,
        authors=new_authors,
        first_publish_year=new_first_publish_year,
        subjects=new_subjects,
        cover_image_url=new_cover_image_url,
        diff=diff,
        has_regression=has_regression,
        regression_fields=regression_fields if regression_fields else None,
    )

    # Update the book row with final values (preserving regressed fields)
    await book_repo.update_book(
        db, tenant_id, book_id,
        title=final_title,
        authors=final_authors,
        first_publish_year=final_first_publish_year,
        subjects=final_subjects,
        cover_image_url=final_cover_image_url,
        current_version=new_version_number,
    )

    return True
