"""
UNITBV OAuth2 Authorization Setup Guide

This document explains the full flow for setting up Microsoft Graph access to UNITBV mailbox.
"""

# STEP 1: Get Authorization URL
# ================================
# Run this locally (NOT in production app):
#
# python -c "
# import asyncio
# from src.app.integrations.email.unitbv_graph_provider import UnitbvGraphProvider
# 
# provider = UnitbvGraphProvider()
# auth_url = provider.get_authorization_url()
# print('OPEN THIS URL IN BROWSER:')
# print(auth_url)
# "
#
# This will output something like:
# https://login.microsoftonline.com/1211f716-5b0b-4bfe-b7c9-8e0045b37e3e/oauth2/v2.0/authorize?
#   client_id=b8420ba5-3f8b-4a29-8bf7-2e26952290fb
#   &redirect_uri=http%3A%2F%2Flocalhost%3A8000%2Fapi%2Fv1%2Fauth%2Funitbv%2Fcallback
#   &response_type=code
#   &scope=Mail.Read+offline_access
#   &state=security_token
#   &prompt=select_account

# STEP 2: User Authorization
# ============================
# 1. Copy the URL
# 2. Open in browser
# 3. Sign in with: rares.ciobanoiu@student.unitbv.ro
# 4. Grant consent (click "Accept")
# 5. Browser will redirect to: http://localhost:8000/api/v1/auth/unitbv/callback?code=...&session_state=...

# STEP 3: Extract Authorization Code
# ====================================
# From the redirect URL, copy the 'code' parameter (long string after "code=")
# Example: code=M.R3_BAY.f7e4...

# STEP 4: Exchange Code for Tokens
# ==================================
# Run this to exchange the code for access + refresh tokens:
#
# python -c "
# import asyncio
# from src.app.integrations.email.unitbv_graph_provider import UnitbvGraphProvider
# 
# async def exchange():
#     provider = UnitbvGraphProvider()
#     auth_code = 'YOUR_CODE_HERE'  # Paste the code from step 3
#     tokens = await provider.exchange_authorization_code(auth_code)
#     print('ACCESS TOKEN:', tokens['access_token'][:50] + '...')
#     print('REFRESH TOKEN:', tokens.get('refresh_token', '')[:50] + '...')
#     print('\nAdd these to .env:')
#     print(f'UNITBV_MICROSOFT_ACCESS_TOKEN={tokens[\"access_token\"]}')
#     print(f'UNITBV_MICROSOFT_REFRESH_TOKEN={tokens.get(\"refresh_token\", \"\")}')
# 
# asyncio.run(exchange())
# "

# STEP 5: Update .env
# ====================
# Copy the output from Step 4 and update .env:
#
# UNITBV_MICROSOFT_ACCESS_TOKEN=eyJ0eXAiOiJKV1QiLCJhbGc...
# UNITBV_MICROSOFT_REFRESH_TOKEN=0.AVsA...

# STEP 6: Test Connection
# ========================
# docker compose exec app python -c "
# import asyncio
# from src.app.integrations.email.factory import get_email_provider
# 
# async def test():
#     provider = get_email_provider('unitbv')
#     emails = await provider.fetch_emails('unitbv')
#     print(f'✅ Success! Found {len(emails)} emails')
#     if emails:
#         print(f'   First: {emails[0].subject}')
# 
# asyncio.run(test())
# "

print("UNITBV OAuth2 Setup Guide - See file for details")
