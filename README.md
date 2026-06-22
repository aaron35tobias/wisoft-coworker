# WiSoft Co-Worker AI Agent
A comprehensive SEO AI agent platform built with Django. It provides an integrated suite of tools for Technical SEO audits, Content Gap analysis, Keyword Research, PageSpeed tracking, and Pricing/PR monitoring, powered by AI (Anthropic Claude & OpenAI).

## Prerequisites
Before you begin, ensure you have the following installed on your machine:
* **Python 3.10+**
* **Node.js** 
* **MySQL Server** 
* **Git**

---

## Local Setup Instructions

**1. Clone the repository**
```bash
git clone https://github.com/prxcode/wisoft-coworker.git
cd wisoft-coworker
```

**2. Backend Setup (Django)**
- Create Virtual Environment: `python -m venv .venv`
- For windows:  `.\.venv\Scripts\Activate.ps1 `
- For mac/linux: `source .venv/bin/activate`
- Install requirements: `pip install -r requirements.txt`

**3. Environment Variables**
- Create a `.env` file in the root directory (use `.env.example` as a reference if available).
- Make sure to configure the AI and Database parameters:

**4. Database & Execution**
- Apply the database schema to your local database: `python manage.py migrate`
- Start server: `python manage.py runserver`
- To check whether the server is running, go to your web browser and enter http://127.0.0.1:8000/ as the URL.
- To sync DB with our models.py: `python manage.py makemigrations` and `python manage.py migrate`
- To run background tasks, start the Celery worker (requires Redis running on port 6379): `celery -A wisoft_co_worker worker -l info --pool=solo`
- To run scheduled automated audits, start Celery Beat: `celery -A wisoft_co_worker beat -l info`

**5. Node Dependencies (If applicable)**
```bash
npm install
```


## Git Workflow & Contribution Guide
To maintain a stable codebase, we use a standard Feature Branch workflow. Do not push directly to the main branch.

#### 1. Create a Feature Branch
```bash
# 1. Go back to the main branch
git checkout main

# 2. Pull main 
git pull origin main

# 3. Create a fresh branch for next task
git checkout -b <user>/<new-task-name>
```

#### 2. Commit your changes
```bash
git add .
git commit -m "feat: add AI summary for technical SEO"
```

Use **Conventional Commits**, They make commit history cleaner and help with changelogs and versioning.

| Prefix      | Meaning                                      | Example                                      |
| ----------- | -------------------------------------------- | -------------------------------------------- |
| `feat:`     | New feature                                  | `feat: add <example>`                        |
| `fix:`      | Bug fix                                      | `fix: resolve <example> issue`               |
| `docs:`     | Documentation only                           | `docs: update README setup instructions`     |
| `style:`    | Formatting, whitespace, no code changes      | `style: format code with black`              |
| `refactor:` | Code restructuring without changing behavior | `refactor: simplify <example> logic`         |
| `perf:`     | Performance improvement                      | `perf: optimize <example>`                   |
| `test:`     | Add or modify tests                          | `test: add unit tests for <example>`         |
| `build:`    | Build system or dependencies                 | `build: upgrade <example> dependency`        |
| `ci:`       | CI/CD changes                                | `ci: add GitHub Actions workflow`            |
| `chore:`    | Misc maintenance                             | `chore: update gitignore`                    |
| `revert:`   | Revert a previous commit                     | `revert: revert <example> changes`           |
| `init:`     | Initial project setup                        | `init: create aegis project structure`       |
| `merge:`    | Branch merge                                 | `merge: combine feature branch into main`    |
| `security:` | Security-related fix                         | `security: sanitize user input handling`     |
| `hotfix:`   | Urgent production fix                        | `hotfix: fix application crash on startup`   |
| `release:`  | Release version preparation                  | `release: prepare v1.0.0 for deployment`     |

#### 3. Push and Open a Pull Request (PR)
```bash
git push origin <feature>/<your-feature-name>
```
Open: `https://github.com/prxcode/wisoft-coworker` and click "SEND PR"

#### 4. Once you all are done with sending PR and your PR is merged by prxcode
```bash
# 1. Go back to the main branch
git checkout main

# 2. Pull main latest code 
git pull origin main

# 3. Delete the old local branch
git branch -d <user>/<fixing-url-input>

# 4. Create a fresh branch for next task
git checkout -b <user>/<new-task-name>
```

#### 5. To pull changes from main branch
To pull the latest updates from the remote `main` branch into your local repository:

If you're currently on `main`

```bash
git checkout main
git pull origin main #This switches to `main` and downloads + merges the latest changes from the remote
git checkout <user>/<url-fix> #Then switch back to your feature branch
git rebase main #Merge `main` into it:
```

Done, now to check what branch you're on [OPTIONAL]

```bash
git branch
```

The current branch will have a `*` next to it.

To see if you're behind the remote [OPTIONAL]

```bash
git fetch origin
git status
```

#### 6. if you want to stash changes which you are working on and then pull requests

```bash
git stash #If you just want to sync main first
git pull origin main #Now your working directory is clean.
git rebase main # or 
git stash pop # Then bring your changes back
```
#### 7. If you don't want the changes which you are working on and want to overwrite with main
```bash
git reset --hard #This deletes current changes
git clean -fd #If you also want to remove untracked files (like new migration files)
git pull origin main # Now you can overwrite
```
#### 8. Review and Merge [ONLY FOR PRIYANSHU]
```bash
git checkout main
git pull origin main
git branch -d feature/your-feature-name
```
