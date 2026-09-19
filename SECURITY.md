# Security

Do not open a public issue for a possible credential leak.

Use GitHub private vulnerability reporting from the Security tab.
Include the affected path, commit, plus secret type.
Do not include the complete secret value.

Runtime secrets belong in private environment files or AWS Systems Manager Parameter Store.
Raw personal data belongs outside this repository.
Git ignores both categories.
