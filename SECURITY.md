# Security

## Reporting a vulnerability

If you find a security issue, please do not open a public GitHub issue. Instead, use GitHub's private vulnerability reporting:

1. Open the repository's **Security** tab.
2. Click **Report a vulnerability**.
3. Describe what you found and how to reproduce it.

I'll respond within a few days and coordinate a fix and disclosure.

## What this tool handles

- Gmail App Passwords for the accounts you point it at, stored in your local `.env`.
- One LLM provider API key of your choice, also in `.env`.
- The metadata of every mail in each connected account: sender, subject, headers, sample subjects, and in mode 3 a short body excerpt per top sender (excluding security-pattern senders).

There is no server side. Everything runs locally on your machine and talks directly to Gmail's IMAP endpoint and your chosen LLM provider.

## What this tool does not do

- It does not send mail.
- It does not permanently delete mail. The destructive action is moving disallowed mail to Trash; Gmail handles permanent removal after its 30-day window.
- It does not exfiltrate credentials. The `.env` is read by the local Python process only.
- It does not call any third-party server beyond your chosen LLM provider and `imap.gmail.com`.

## Hardening recommendations

If you fork or deploy this for someone else:

- Bind Streamlit to `127.0.0.1` (`--server.address 127.0.0.1`) unless you specifically need network access. The default `0.0.0.0` exposes the UI to your LAN, including the form that writes Gmail App Passwords to `.env`.
- Keep `.env` out of any shared drive or backup that other people can read.
- Rotate the App Password if you ever paste it somewhere it shouldn't have gone (logs, screenshots, chat). Generation is free at https://myaccount.google.com/apppasswords.
- Use a provider key with usage limits (most providers let you cap monthly spend) so a runaway loop can't drain your account.
