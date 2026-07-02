#!/usr/bin/env python3
from __future__ import annotations

import os
from sqlalchemy import create_engine, text
from passlib.context import CryptContext

DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql+psycopg://postgres:postgres@localhost:5432/bizintel')
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', 'admin@example.com')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'change-me-now')
ADMIN_NAME = os.getenv('ADMIN_NAME', 'System Admin')

pwd_context = CryptContext(schemes=['bcrypt'], deprecated='auto')
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

with engine.begin() as conn:
    conn.execute(text('''
        INSERT INTO app.users (full_name, email, password_hash, role)
        VALUES (:name, :email, :password_hash, 'super_admin')
        ON CONFLICT (email) DO UPDATE
        SET role = 'super_admin', is_active = TRUE
    '''), {'name': ADMIN_NAME, 'email': ADMIN_EMAIL.lower(), 'password_hash': pwd_context.hash(ADMIN_PASSWORD)})
print(f'Super admin ready: {ADMIN_EMAIL}')
