
# Due Diligence Copilot

### AI-Assisted Document-Driven Financial & Corporate Due Diligence Platform

Due Diligence Copilot is a reusable Streamlit-based application that helps users analyze company documents, extract structured evidence, reconcile inconsistencies, evaluate financial performance, identify risks, and generate AI-assisted diligence insights.

The platform is designed to support document-driven due diligence without hardcoding company-specific information into the application workflow.

## Key Features

- Multi-format document ingestion (PDF, XLSX, PPTX)
- Automatic document classification
- Evidence extraction and structured evidence storage
- Cross-document reconciliation
- Financial metric analysis and validation
- Risk register generation
- AI-assisted executive summaries
- Evidence-grounded diligence Q&A
- Management question generation
- Interactive financial and risk dashboards
- Deterministic fallback when AI services are unavailable

## Workflow

User Upload → Document Classification → Document Extraction → Evidence Store → Reconciliation Engine → Financial Engine → Risk Engine → AI Analysis → Interactive Dashboard

## Technology Stack

- Python
- Streamlit
- Pandas
- Plotly
- Excel and PDF document processing
- Google Gemini API
- Python-based financial and reconciliation logic

## Project Architecture

```text
Due Diligence Copilot/
├── app.py
├── src/
│   ├── document_extractor.py
│   ├── document_classifier.py
│   ├── evidence_engine.py
│   ├── reconciliation_engine.py
│   ├── financial_engine.py
│   ├── risk_engine.py
│   ├── ai_engine.py
│   └── utils.py
├── Company Docs/
├── assets/
├── requirements.txt
└── .gitignore
```

## Core Modules

| Module | Purpose |
|---|---|
| Document Extractor | Extracts content from supported documents |
| Document Classifier | Identifies document types |
| Evidence Engine | Structures extracted evidence |
| Reconciliation Engine | Identifies inconsistencies across documents |
| Financial Engine | Calculates and validates financial metrics |
| Risk Engine | Builds a structured risk register |
| AI Engine | Generates summaries, explanations, and diligence responses |

## Demonstration

The included demonstration uses synthetic company documents representing:

- Financial statements
- Bank statements
- Customer metrics
- Capitalization table
- Investor presentation
- Legal and corporate diligence records

The application identifies inconsistencies and presents them through the financial, risk, and reconciliation interfaces.

**All demonstration data is synthetic and intended for educational and portfolio demonstration purposes.**

## Example Analysis Capabilities

The application can help identify:

- Differences in reported customer counts
- Variances between modelled and bank-reported cash balances
- Ownership inconsistencies
- Negative profitability indicators
- Liquidity concerns
- Legal and compliance documentation gaps

## AI and Reliability Approach

The application separates deterministic calculations from AI-generated interpretation.

- Financial metrics and reconciliation checks are calculated using Python logic.
- AI is used for explanations, summaries, management questions, and interactive diligence responses.
- The application is designed to avoid unsupported conclusions when evidence is unavailable.
- A deterministic fallback is available when AI services cannot be accessed.

## Local Setup

### 1. Clone the repository

```bash
git clone https://github.com/KanishSharma554/Due-diligence-copilot.git
cd Due-diligence-copilot
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure the AI API

Create a `.env` file in the project root and add your Gemini API key.

Never commit API keys or other secrets to GitHub.

### 4. Run the application

```bash
streamlit run app.py
```

The application will open in your browser.

## Project Objectives

This project demonstrates the application of:

- Document processing
- Data extraction
- Financial analysis
- Data reconciliation
- Risk identification
- AI-assisted analytical workflows
- Interactive dashboard development

## Limitations

This is a portfolio demonstration and not a substitute for professional legal, financial, tax, or investment due diligence.

The quality of results depends on the completeness and accuracy of the uploaded documents.

## Author

**Kanish Sharma**
