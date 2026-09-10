import asyncio
from datetime import datetime, timezone
from sqlalchemy import select, text
from src.app.database.session import AsyncSessionLocal, engine
from src.app.database.models.models import (
    AcademicYear, User, EmailAccount, UserMemory, ActionItem, PriorityEnum, ActionStatusEnum
)
from src.app.core.logging import logger


async def seed_database():
    logger.info("Checking database schema installed by Alembic...")
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1 FROM alembic_version LIMIT 1"))

    async with AsyncSessionLocal() as session:
        # 1. Seed Academic Years
        for year, is_active in [("2024-2025", False), ("2025-2026", False), ("2026-2027", True)]:
            res = await session.execute(select(AcademicYear).where(AcademicYear.year_code == year))
            if not res.scalar_one_or_none():
                session.add(AcademicYear(year_code=year, is_active=is_active))
                logger.info(f"Seeded AcademicYear: {year}")

        # 2. Seed Default User
        res = await session.execute(select(User).where(User.telegram_chat_id == "123456789"))
        if not res.scalar_one_or_none():
            session.add(User(telegram_chat_id="123456789", full_name="Student UNITBV", preferred_language="ro"))
            logger.info("Seeded default student user.")

        # 3. Seed Email Accounts
        for acc_type, address in [("personal", "user.personal@example.com"), ("unitbv", "student.unitbv@student.unitbv.ro")]:
            res = await session.execute(select(EmailAccount).where(EmailAccount.email_address == address))
            if not res.scalar_one_or_none():
                session.add(EmailAccount(account_type=acc_type, email_address=address, is_active=True))
                logger.info(f"Seeded EmailAccount: {address}")

        # 4. Seed User Memories
        for key, val, cat in [
            ("preferred_language", "ro", "preference"),
            ("important_senders", "secretariat.fiesc@unitbv.ro, decanat@unitbv.ro", "rule"),
            ("default_calendar_summary_hour", "08:00", "preference"),
        ]:
            res = await session.execute(select(UserMemory).where(UserMemory.key == key))
            if not res.scalar_one_or_none():
                session.add(UserMemory(key=key, value=val, category=cat))
                logger.info(f"Seeded UserMemory: {key}")

        # 5. Seed Initial Action Item
        res = await session.execute(select(ActionItem).where(ActionItem.title == "Completare Convenție de Practică"))
        if not res.scalar_one_or_none():
            session.add(ActionItem(
                title="Completare Convenție de Practică",
                source="practice",
                priority=PriorityEnum.HIGH,
                status=ActionStatusEnum.OPEN,
                source_reference="Ghid_Practica_2026_2027.md"
            ))
            logger.info("Seeded default practice ActionItem.")

        await session.commit()
        logger.info("Database seeding completed successfully.")


if __name__ == "__main__":
    asyncio.run(seed_database())
