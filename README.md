# LangChain Deep Agents

Collection of projects dedicated to AI agent development and research.

## **Getting Started Guide**

### **1. Update the Project**

First, make sure you're on the correct branch and that your code is up to date:

```
git checkout production
git pull
git checkout -b your-branch-name
```

---

### **2. Create the Virtual Environment**

> **Requirement:** Python 3.14 or higher (version pinned in `.python-version`).
>

Create a virtual environment to isolate the project's dependencies:

```
python -m venv .venv
```

---

### **3. Activate the Virtual Environment**

#### **PowerShell**

```
.\.venv\Scripts\Activate.ps1
```

#### **CMD**

```
.venv\Scripts\activate.bat
```

After activation, your terminal should look like this:

```
(.venv) PS C:\Users\username\better-ai>
```

---

### **4. Install Dependencies**

You can install the dependencies in two ways:

#### **Using uv (recommended)**

```
uv sync
```

---

### **5. Set Up Environment Variables**

Create a `.env` file in the project root with the following variables:

| **Variable** | **Description** |
| --- | --- |
| `ENV_NAME` | --- |

```
# LLM's
OPENAI_API_KEY=********************
GEMINI_API_KEY=********************
GROQ_API_KEY=********************
ANTHROPIC_API_KEY=********************
```