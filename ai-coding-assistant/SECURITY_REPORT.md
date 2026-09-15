# Hybrid Security & Performance Scan Report

**Summary:** LLM Triage failed. Returning raw findings.

### [ERROR] dockerfile.security.missing-user.missing-user
- **File:** `backend/Dockerfile:11`
- **Details:** By not specifying a USER, a program in the container may run as 'root'. This is a security hazard. If an attacker can control a process running as root, they may have control over the container. Ensure that the last USER in a Dockerfile is a USER other than 'root'.

### [ERROR] python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
- **File:** `backend/app/database.py:334`
- **Details:** Avoiding SQL string concatenation: untrusted input concatenated with raw SQL query can result in SQL Injection. In order to execute raw query safely, prepared statement should be used. SQLAlchemy provides TextualSQL to easily used prepared statement with named parameters. For complex SQL composition, use SQL Expression Language or Schema Definition Language. In most cases, SQLAlchemy ORM will be a better option.

### [ERROR] python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
- **File:** `backend/app/database.py:448`
- **Details:** Avoiding SQL string concatenation: untrusted input concatenated with raw SQL query can result in SQL Injection. In order to execute raw query safely, prepared statement should be used. SQLAlchemy provides TextualSQL to easily used prepared statement with named parameters. For complex SQL composition, use SQL Expression Language or Schema Definition Language. In most cases, SQLAlchemy ORM will be a better option.

### [WARNING] python.flask.security.xss.audit.direct-use-of-jinja2.direct-use-of-jinja2
- **File:** `backend/app/prompt_library.py:11`
- **Details:** Detected direct use of jinja2. If not done properly, this may bypass HTML escaping which opens up the application to cross-site scripting (XSS) vulnerabilities. Prefer using the Flask method 'render_template()' and templates with a '.html' extension in order to prevent XSS.

### [ERROR] python.lang.security.audit.subprocess-shell-true.subprocess-shell-true
- **File:** `backend/app/test_runner.py:82`
- **Details:** Found 'subprocess' function 'run' with 'shell=True'. This is dangerous because this call will spawn the command using a shell process. Doing so propagates current shell settings and variables, which makes it much easier for a malicious actor to execute commands. Use 'shell=False' instead.

### [ERROR] python.lang.security.audit.subprocess-shell-true.subprocess-shell-true
- **File:** `backend/app/workspace_tools.py:27`
- **Details:** Found 'subprocess' function 'run' with 'shell=True'. This is dangerous because this call will spawn the command using a shell process. Doing so propagates current shell settings and variables, which makes it much easier for a malicious actor to execute commands. Use 'shell=False' instead.

### [WARNING] yaml.docker-compose.security.no-new-privileges.no-new-privileges
- **File:** `docker-compose.yml:26`
- **Details:** Service 'frontend' allows for privilege escalation via setuid or setgid binaries. Add 'no-new-privileges:true' in 'security_opt' to prevent this.

### [WARNING] yaml.docker-compose.security.writable-filesystem-service.writable-filesystem-service
- **File:** `docker-compose.yml:26`
- **Details:** Service 'frontend' is running with a writable root filesystem. This may allow malicious applications to download and run additional payloads, or modify container files. If an application inside a container has to save something temporarily consider using a tmpfs. Add 'read_only: true' to this service to prevent this.

### [WARNING] yaml.docker-compose.security.no-new-privileges.no-new-privileges
- **File:** `docker-compose.yml:37`
- **Details:** Service 'qdrant' allows for privilege escalation via setuid or setgid binaries. Add 'no-new-privileges:true' in 'security_opt' to prevent this.

### [WARNING] yaml.docker-compose.security.writable-filesystem-service.writable-filesystem-service
- **File:** `docker-compose.yml:37`
- **Details:** Service 'qdrant' is running with a writable root filesystem. This may allow malicious applications to download and run additional payloads, or modify container files. If an application inside a container has to save something temporarily consider using a tmpfs. Add 'read_only: true' to this service to prevent this.

### [WARNING] yaml.docker-compose.security.no-new-privileges.no-new-privileges
- **File:** `docker-compose.yml:44`
- **Details:** Service 'searxng' allows for privilege escalation via setuid or setgid binaries. Add 'no-new-privileges:true' in 'security_opt' to prevent this.

### [WARNING] yaml.docker-compose.security.writable-filesystem-service.writable-filesystem-service
- **File:** `docker-compose.yml:44`
- **Details:** Service 'searxng' is running with a writable root filesystem. This may allow malicious applications to download and run additional payloads, or modify container files. If an application inside a container has to save something temporarily consider using a tmpfs. Add 'read_only: true' to this service to prevent this.

### [ERROR] dockerfile.security.missing-user.missing-user
- **File:** `frontend/Dockerfile:10`
- **Details:** By not specifying a USER, a program in the container may run as 'root'. This is a security hazard. If an attacker can control a process running as root, they may have control over the container. Ensure that the last USER in a Dockerfile is a USER other than 'root'.

### [WARNING] problem-based-packs.insecure-transport.js-node.http-request.http-request
- **File:** `vscode-extension/extension.js:201`
- **Details:** Checks for requests sent to http:// URLs. This is dangerous as the server is attempting to connect to a website that does not encrypt traffic with TLS. Instead, only send requests to https:// URLs.

### [WARNING] problem-based-packs.insecure-transport.js-node.using-http-server.using-http-server
- **File:** `vscode-extension/extension.js:212`
- **Details:** Checks for any usage of http servers instead of https servers. Encourages the usage of https protocol instead of http, which does not have TLS and is therefore unencrypted. Using http can lead to man-in-the-middle attacks in which the attacker is able to read sensitive information.

### [WARNING] problem-based-packs.insecure-transport.js-node.http-request.http-request
- **File:** `vscode-extension/extension.js:232`
- **Details:** Checks for requests sent to http:// URLs. This is dangerous as the server is attempting to connect to a website that does not encrypt traffic with TLS. Instead, only send requests to https:// URLs.

### [WARNING] problem-based-packs.insecure-transport.js-node.using-http-server.using-http-server
- **File:** `vscode-extension/extension.js:239`
- **Details:** Checks for any usage of http servers instead of https servers. Encourages the usage of https protocol instead of http, which does not have TLS and is therefore unencrypted. Using http can lead to man-in-the-middle attacks in which the attacker is able to read sensitive information.

### [WARNING] problem-based-packs.insecure-transport.js-node.http-request.http-request
- **File:** `vscode-extension/extension.js:258`
- **Details:** Checks for requests sent to http:// URLs. This is dangerous as the server is attempting to connect to a website that does not encrypt traffic with TLS. Instead, only send requests to https:// URLs.

### [WARNING] problem-based-packs.insecure-transport.js-node.using-http-server.using-http-server
- **File:** `vscode-extension/extension.js:265`
- **Details:** Checks for any usage of http servers instead of https servers. Encourages the usage of https protocol instead of http, which does not have TLS and is therefore unencrypted. Using http can lead to man-in-the-middle attacks in which the attacker is able to read sensitive information.

### [WARNING] problem-based-packs.insecure-transport.js-node.http-request.http-request
- **File:** `vscode-extension/extension.js:284`
- **Details:** Checks for requests sent to http:// URLs. This is dangerous as the server is attempting to connect to a website that does not encrypt traffic with TLS. Instead, only send requests to https:// URLs.

### [WARNING] problem-based-packs.insecure-transport.js-node.using-http-server.using-http-server
- **File:** `vscode-extension/extension.js:291`
- **Details:** Checks for any usage of http servers instead of https servers. Encourages the usage of https protocol instead of http, which does not have TLS and is therefore unencrypted. Using http can lead to man-in-the-middle attacks in which the attacker is able to read sensitive information.

