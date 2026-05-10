# Demos

Sample outputs showing what each step produces. After your first run, real outputs land in `data/<account-email>/` and you can sanitize one to drop here.

Files (planned, none are committed yet):
- `inventory.sample.json`, anonymized stats from a real run with top senders renamed
- `report.sample.md`, the human-readable summary that pairs with it
- `allowed.sample.txt`, auto-generated keep-list
- `disallowed.sample.txt`, auto-generated trash-list
- `screenshot-streamlit.png`, Streamlit UI screenshot

How to add the screenshot:

1. Run the four cards through to apply on a real account.
2. Take a screenshot of the Streamlit UI in a state worth showing (for example, Card 3 with both tables populated).
3. Crop out anything identifying: the sender column, the address bar, account picker.
4. Save as `demos/screenshot-streamlit.png` and commit.

How to add sanitized data:

1. Copy `data/<your-account>/inventory.json` to `demos/inventory.sample.json`.
2. Replace real sender addresses with `sender-1@example.com`, `sender-2@example.com`, etc., keeping the counts so the shape is realistic.
3. Repeat for `report.md`, `allowed.txt`, `disallowed.txt`.
