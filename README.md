# SailRanks Automation Client

A small Python command-line client for authorised SailRanks administration. It automates login, regatta creation, adding players, submitting single-race results, retrieving results, and exporting parsed results to JSON or CSV.

Use this tool only with a SailRanks account and regattas that you are authorised to administer. The tool sends the same form fields observed in the supplied browser requests; it is not an official SailRanks API client.

## Features

- Logs in using an already-generated SailRanks V2 password hash.
- Maintains the authenticated session cookie automatically.
- Creates regattas.
- Adds players to a regatta.
- Submits finishing positions and DNS entries for one race.
- Retrieves the HTML regatta results page.
- Parses the embedded `tabledata` JavaScript array.
- Displays results in a terminal table.
- Exports results to JSON or CSV.
- Logs requests and responses with sensitive values redacted.

## Requirements

- Python 3.10 or newer.
- A SailRanks account with the required organiser permissions.
- A pre-generated SailRanks V2 password hash.
- Network access to `https://sailranks.com`.

The script expects the password hash, not the plaintext SailRanks password. It does not generate, hash, trim, or otherwise modify the value.

## Installation

Open PowerShell in the directory containing `sailranks_automation.py`.

Create and activate a virtual environment:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install the dependencies with regular `pip`:

```powershell
python -m pip install requests beautifulsoup4 python-dotenv
```

Verify the installation:

```powershell
python --version
python -m pip show requests beautifulsoup4 python-dotenv
```

## `.env` credentials

Create a `.env` file beside `sailranks_automation.py`:

```text
SAILRANKS_USERNAME=your-sailranks-username
SAILRANKS_PASSWORD_HASH=your-pre-generated-v2-hash
```

The tool loads these values automatically when it starts:

| Variable | Required | Purpose |
|---|---:|---|
| `SAILRANKS_USERNAME` | Yes | SailRanks username. |
| `SAILRANKS_PASSWORD_HASH` | Yes | Already-generated SailRanks V2 password hash. |
| `SAILRANKS_BASE_URL` | No | Server base URL. Defaults to `https://sailranks.com`. |
| `SAILRANKS_TIMEOUT` | No | HTTP timeout in seconds. Defaults to `30`. |
| `SAILRANKS_LOG_FILE` | No | Log file path. Defaults to `sailranks.log`. |
| `SAILRANKS_LOG_LEVEL` | No | Logging level. Defaults to `INFO`. |

### Verify credentials without displaying the hash

```powershell
python -c "from dotenv import dotenv_values; values = dotenv_values('.env'); print('Username set:', bool(values.get('SAILRANKS_USERNAME'))); print('Hash set:', bool(values.get('SAILRANKS_PASSWORD_HASH'))); print('Hash length:', len(values.get('SAILRANKS_PASSWORD_HASH', '')))"
```

Do not print the actual hash or commit `.env` to a repository.

## Login

Test authentication:

```powershell
python .\sailranks_automation.py login
```

A successful login displays:

```text
Login completed.
```

The client first requests `/v/login` to establish a session cookie, then posts the login form to `/v/login`. It confirms success by checking for the authenticated home page, the `/v/manage` link, or the `/v/logout` form.

A failed login raises an error rather than treating every `200 OK` response as successful. SailRanks can return `200 OK` for both successful and failed login attempts, so the HTML content is checked.

## Create a regatta

```powershell
python .\sailranks_automation.py create-regatta `
    --name "Test Regatta" `
    --category "Test1" `
    --format "Fleet+MR" `
    --description "Short description" `
    --long-description "Long description"
```

Optional editor value:

```powershell
python .\sailranks_automation.py create-regatta `
    --name "Test Regatta" `
    --category "Test1" `
    --format "Fleet+MR" `
    --editor owner
```

The request uses these form fields:

```text
name
category
format
description
LongDesc
editor
formAction=createRegatta
```

The server response is logged. The current basic version does not automatically extract a newly created regatta ID from the response, so inspect the response or SailRanks page if you need the ID for a later command.

## Add players

Use the exact player strings accepted by SailRanks:

```powershell
python .\sailranks_automation.py add-players 12631 `
    "5835 - Jerseytbw - [JEY]" `
    "6504 - Jakob - [DEN]" `
    "6785 - MudCreek - [CAN]"
```

The first positional value is the regatta ID. The remaining values are player entries.

To enter players interactively with Tab completion from `players.txt`, omit the player arguments:

```powershell
python .\sailranks_automation.py add-players 12631
```

Enter a player on each prompt. Press Tab to complete a matching entry, Enter to accept it, and Enter on a blank prompt to submit the selected players. Use `--players-file` to complete from a different file.

You can also place entries in a text file, one player per line:

```text
5835 - Jerseytbw - [JEY]
6504 - Jakob - [DEN]
6785 - MudCreek - [CAN]
```

Then run:

```powershell
python .\sailranks_automation.py add-players 12631 .\players.txt
```

The generated request uses:

```text
cver=13
batchPlayersToAdd=<one player per line>
formAction=addPlayerToRegatta
```

## Submit race results

Finishing entries are supplied in finishing order. DNS entries are supplied separately:

```powershell
python .\sailranks_automation.py submit-result 12631 `
    --race-id 1 `
    --finish "JEY 5835 Jerseytbw" `
    --finish "DEN 6504 Jakob" `
    --dns "CAN 6785 MudCreek"
```

This produces fields equivalent to:

```text
raceID=1
radix=bnmlaaxudq
nbEntries=3
formAction=submitSingleRaceResult
bnmlaaxudq_p1=JEY 5835 Jerseytbw
bnmlaaxudq_p2=DEN 6504 Jakob
batchDNS=CAN 6785 MudCreek
```

The order of repeated `--finish` options determines the finishing positions. DNS means Did Not Start and is sent through `batchDNS`.

To enter results interactively with Tab completion from `players.txt`, omit both `--finish` and `--dns`:

```powershell
python .\sailranks_automation.py submit-result 12631 --race-id 1
```

Select finishing players in order, press Enter on a blank prompt, then select DNS players. Use `--players-file` to complete from a different player list.

Entries can also be read from files. For example, `finish.txt`:

```text
JEY 5835 Jerseytbw
DEN 6504 Jakob
```

and `dns.txt`:

```text
CAN 6785 MudCreek
```

Run:

```powershell
python .\sailranks_automation.py submit-result 12631 `
    --race-id 1 `
    --finish .\finish.txt `
    --dns .\dns.txt
```

## Retrieve results

Display the parsed results as a terminal table:

```powershell
python .\sailranks_automation.py results 12631
```

The parser extracts the `tabledata` array embedded in the HTML response and reads fields such as:

- `_id` — player ID.
- `rank` — current ranking.
- `name` — player name.
- `country` — country code.
- `sail` — displayed sail identifier.
- `totalPoints` — net points.
- `fullPoints` — total points before discards.
- `r1`, `r2`, `r3`, and so on — race results.
- `mr` — medal race result.

Output as JSON:

```powershell
python .\sailranks_automation.py results 12631 --json
```

Export to CSV:

```powershell
python .\sailranks_automation.py results 12631 --csv .\results.csv
```

Retrieve the raw HTML page:

```powershell
python .\sailranks_automation.py results 12631 --raw
```

Request the linked API endpoint instead:

```powershell
python .\sailranks_automation.py results 12631 --api
```

The `--api` option currently prints the API response without applying the HTML result parser because the API response format has not been captured and validated.

## Retrieve an arbitrary page

The `page` command performs an authenticated GET request and prints the response:

```powershell
python .\sailranks_automation.py page /v/regattas/12631
```

## Logging

By default, exchanges are written to:

```text
sailranks.log
```

Each entry includes:

- Timestamp.
- Operation name.
- HTTP method.
- URL.
- Request form data.
- HTTP status code.
- Response headers.
- Response body.
- Request duration.

The following values are redacted before logging:

- `pwwd`.
- Cookies and session cookies.
- Authorization headers.
- Password fields.
- Access and refresh tokens.
- API keys and secrets.

Change the log location:

```powershell
$env:SAILRANKS_LOG_FILE = "C:\Users\admin\Documents\SailRanks Test\logs\sailranks.log"
```

Set a less verbose level:

```powershell
$env:SAILRANKS_LOG_LEVEL = "WARNING"
```

## Troubleshooting

### The script reports missing credentials

Check that `.env` exists beside `sailranks_automation.py` and contains both variables:

```text
SAILRANKS_USERNAME=your-sailranks-username
SAILRANKS_PASSWORD_HASH=your-pre-generated-v2-hash
```

Check the values without displaying them:

```powershell
python -c "from dotenv import dotenv_values; values = dotenv_values('.env'); print('Username set:', bool(values.get('SAILRANKS_USERNAME'))); print('Hash set:', bool(values.get('SAILRANKS_PASSWORD_HASH')))"
```

It should report both values as set:

```text
Username set: True
Hash set: True
```

### The script reports an unauthenticated page

Check that:

- The username is correct.
- The value is the SailRanks V2 hash, not the plaintext password.
- The hash was generated for the same username.
- The hash has not been copied with surrounding quotes or spaces.
- The account can log in through the normal SailRanks website.
- The system clock and network connection are working normally.

### `ModuleNotFoundError: No module named 'dotenv'`

Install the dependencies into the active virtual environment:

```powershell
python -m pip install -e .
```

### `ModuleNotFoundError: No module named 'requests'`

Install dependencies into the active virtual environment:

```powershell
python -m pip install -e .
```

Confirm that the virtual environment is active. The prompt should contain:

```text
(.venv)
```

### Results show no rows

Use the raw option:

```powershell
python .\sailranks_automation.py results 12631 --raw > regatta.html
```

Then check whether the page contains:

```javascript
var tabledata = [
```

The parser currently expects the generated HTML structure supplied during development. If SailRanks changes that structure, the parser may need updating.

### An operation returns HTTP 200 but does not appear to work

SailRanks uses HTML responses, and an HTTP `200 OK` does not necessarily confirm that a form operation succeeded. Inspect the logged response body and check the resulting regatta page in a browser.

## Security considerations

- Do not commit `SAILRANKS_PASSWORD_HASH` to Git.
- Do not share `sailranks.log` if it contains account or event information.
- Do not share live session cookies.
- Treat a copied session cookie as a credential and invalidate it if exposed.
- Use the tool only against SailRanks accounts and regattas you are authorised to manage.
- Test destructive or scoring-related operations on a test regatta first.

A useful `.gitignore` file is:

```gitignore
.venv/
__pycache__/
*.pyc
sailranks.log
logs/
.env
results.csv
```

## Example workflow

```powershell
# Activate the environment
.\.venv\Scripts\Activate.ps1

# Create .env from the template, then fill in your credentials
Copy-Item .env.example .env

# Test authentication
python .\sailranks_automation.py login

# Create a test regatta
python .\sailranks_automation.py create-regatta `
    --name "Test Regatta" `
    --category "Test1" `
    --format "Fleet+MR"

# Add known players to regatta 12631
python .\sailranks_automation.py add-players 12631 `
    "5835 - Jerseytbw - [JEY]" `
    "6504 - Jakob - [DEN]" `
    "6785 - MudCreek - [CAN]"

# Submit one race result
python .\sailranks_automation.py submit-result 12631 `
    --race-id 1 `
    --finish "JEY 5835 Jerseytbw" `
    --finish "DEN 6504 Jakob" `
    --dns "CAN 6785 MudCreek"
> Note
>
> To add the medal race it is just the final race number, so if you have `5` races + medal race then medal race will be `6`
>

# Retrieve and export results
python .\sailranks_automation.py results 12631
python .\sailranks_automation.py results 12631 --csv .\results.csv
```
