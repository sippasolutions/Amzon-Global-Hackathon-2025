# Team & Lineage

## Project Team

### Technical Development
- **Dr. Bon Sy (Team Lead)** — SIPPA Solutions Inc., Queens College and The Graduate Center, CUNY  
- **Ms. Samiha Zaman** — Queens College, CUNY  

### Clinical Consultation
- **Dr. Issac Sachmechi** - Queens Hospital/NYC Health and Hospitals
- **Dr. Avraham Ben-Haim** - Queens Hospital/NYC Health and Hospitals

---

# Project Lineage: SIPPA Solutions & CUNY

**SIPPA Solutions Inc.** is a CUNY-based startup dedicated to developing a digital health platform that empowers individuals to leverage their personal data for better health outcomes.

In partnership with Queens College/CUNY, SIPPA Solutions has secured over **$1.3 million in NSF funding** across multiple rounds. This funding has supported the development of a **digital therapeutic solution for diabetes**, integrating behavioral interventions with robust technical validation.

This comprehensive effort was recognized with the **Best Paper Award** at a leading international conference in health informatics. The project has since advanced to a **clinical trial stage (NCT07032311)**, directed by **Dr. Sachmechi**, Director of the Diabetes Center of Excellence at **NYC Health + Hospitals/Queens**. This trial investigates how AI-assisted behavioral interventions, adjunctive to standard care, can improve patient outcomes and enhance clinical workflow efficiency.

---

# Problem & Solution

## Major Pain Point

A critical and mandatory step in behavioral intervention is the creation of **S.M.A.R.T. goals** (Specific, Measurable, Actionable, Relevant, and Time-bounded), which must be precisely tailored to a patient’s specific medical condition (e.g., diabetes, liver disease).

Currently, clinicians or residents must manually review electronic medical records (EMR) and draft these goals. In our clinical investigation, this process has proven **time-intensive and resource-demanding**, requiring both specialized medical expertise and strict adherence to regulatory compliance standards.

## Ideation: AI-Powered Goal Generation

Leveraging our combined expertise in **AI/ML** and **clinical care delivery**, the team proposes an **AI agent system for automated S.M.A.R.T. goal generation**. This approach is designed to:

- Automate and streamline behavioral intervention workflows  
- Significantly reduce clinician workload  
- Enhance the scalability of clinical decision support  

---

# Proof-of-Concept (PoC) for the Amazon Global Hackathon

## Project Scope & Platform

This project serves as a **proof-of-concept (PoC)** demonstrating the feasibility of using the **Amazon Bedrock AgentCore** platform. The goal is to establish a **multi-agent, scalable AI environment** complete with **enterprise-grade security, observability, and flexibility**.

## Prototype Specifications

### Scalability & Security

The core system consists of two independent AgentCore runtimes:

1. **Smart-Goal-Generator Agent**  
2. **LLM-Evaluator Agent (LLM-as-Judge)**  

Each agent runs in an **isolated AgentCore runtime kernel** to perform two coordinated tasks:

- Generating S.M.A.R.T. goals from clinician summary notes in EMRs.  
- Evaluating the quality of these goals using the LLM-as-Judge agent.  

### Flexibility

- **Interchangeable LLMs:** Each agent supports seamless substitution of underlying LLMs, regardless of whether the chosen Bedrock model supports system prompts or tools.  
- **Shared Functionality:** Agents share functionalities as tools via the **Model Context Protocol (MCP)**.  

### Enterprise-Grade Security

- MCP tools are provisioned through **AWS Lambda**.  
- **AgentCore API Gateway** uses **OAuth2** for secure authorization of all service requests.  

### Observability

- **Amazon CloudWatch** provides runtime logging for effective monitoring, maintenance, and auditing.  

---

# Development Resources and Building Blocks

## Toolkits & Libraries
- Bedrock AgentCore Application Starter Toolkit  
- Strands & Bedrock Libraries:  
  - `strands-agents`  
  - `strands-agents-tools`  
  - `boto3>=1.40.8`  
  - `botocore>=1.40.8`  
  - `bedrock-agentcore>=0.1.2`  
  - `bedrock-agentcore-starter-toolkit>=0.1.5`  

## Core Building Blocks
- **AgentCore API Gateway**  
- **AWS Cognito** for authentication, re-authentication, and MCP server pool maintenance.  
- **AWS Systems Manager Parameter Store** for maintaining runtime ARNs, Lambda ARNs, IAM roles, API Gateway credentials, and other configuration parameters.  
- **Amazon ECR** for containerized deployment of AgentCore runtime Docker images.  
- **Bedrock-hosted LLMs** (no external model endpoints via SageMaker are included in this PoC).  

---

# System Architecture and Deliverables

## System Architecture
📊 [Architecture Diagram](https://tinyurl.com/yc54fr54)

## Final Prototype Deliverables
- **GitHub Repository:** [https://tinyurl.com/37saectr](https://tinyurl.com/37saectr)  
- **IAM Roles & Policies for Replication:** [https://tinyurl.com/2whmjuzf](https://tinyurl.com/2whmjuzf)  
  *(Note: Certain runtime and account-specific configurations may require adjustment.)*  
- **Demo Showcase (Deployment Walkthrough):**  
1. High level (3-min video): https://youtu.be/Wz7EpyvTvyE
2. Unit testing (step-by-step walkthrough) of Smart-Goal-Generator and LLM-Evaluator agents: https://tinyurl.com/t2uz7ptm (just open the Jupyter Notebook)


---

# Contact

**Dr. Bon Sy**  
📧 bsy@sippasolutions.com | bon.sy@qc.cuny.edu  
