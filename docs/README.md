# Documentation Hub

This page routes contributors, operators, and reviewers to the right guides.

## Who this is for
- Developers building features or fixing bugs
- Operators/SRE handling runbooks and smokes
- Testers/QA validating flows
- PM/Stakeholders needing architecture and policies

## Start here
- Developer guides: [dev_guide.md](dev_guide.md)
- Architecture: [architecture.md](architecture.md)
- Technical design (API/contracts): [tdd.md](tdd.md)
- Cookbooks (how-tos): [cookbooks/README.md](cookbooks/README.md)
- Runbooks (operational): [runbooks/README.md](runbooks/README.md)
- Testing and TDD: [testing/README.md](testing/README.md)
- Configuration reference: [config/README.md](config/README.md)
- Security and compliance: [iam.md](iam.md), [compliance.md](compliance.md), [confidentiality_agreement.md](confidentiality_agreement.md)
- Release and deployment: [release/README.md](release/README.md)
- Policies and roles: [policies/](policies/) and [contributors.md](contributors.md)
- Glossary and FAQs: [glossary.md](glossary.md)

## How to use this folder
- Run a local stack: [cookbooks/README.md](cookbooks/README.md) → [cookbooks/bootstrap_sandbox.md](cookbooks/bootstrap_sandbox.md) → [cookbooks/smoke_test.md](cookbooks/smoke_test.md)
- Debug ingestion/search: [runbooks/README.md](runbooks/README.md) → console runbooks; data/model details in [tdd.md](tdd.md) and [architecture.md](architecture.md)
- Prepare a release: [release/README.md](release/README.md) → [cookbooks/smoke_test.md](cookbooks/smoke_test.md) → [tdd.md](tdd.md) for contract changes

## How to find what you need
- Need local setup or workflow? See developer guides.
- Need to run or triage a job? Start with runbooks; if you are setting up, use cookbooks.
- Need data/contract context? Check architecture and config reference.
- Need compliance or IAM details? Use security and compliance.
- Need to add tests or understand coverage? Use testing and TDD.
- Shipping a release or migration? See release and deployment.

## Contribute
Keep links current when adding new docs. Prefer short pages with links back to this hub.
