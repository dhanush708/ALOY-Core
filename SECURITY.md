# Security Policy

We take the security and privacy of ALOY seriously. Because ALOY is a local-first desktop application, protecting your workspace and local environment is a joint responsibility. This policy outlines how security vulnerabilities are handled and how users can keep their installation secure.

---

## 1. Reporting a Vulnerability
If you discover a security vulnerability in ALOY, please report it directly to the Creator. 
- **Reporting Email**: [anbudhanush31@gmail.com](mailto:anbudhanush31@gmail.com)
- **What to Include**:
  - A description of the vulnerability and its potential impact.
  - Detailed step-by-step reproduction instructions (and code snippets if applicable).
  - Information about your operating system version and ALOY version.

Please do **NOT** open public issues on GitHub for suspected security vulnerabilities. Allow the Creator reasonable time to review, patch, and release a fix before public disclosure.

## 2. Expected Response Process
Upon receiving a vulnerability report:
1. **Acknowledgement**: The Creator will acknowledge receipt of your report within 48 business hours.
2. **Investigation & Triage**: The Creator will investigate the vulnerability to determine severity and impact.
3. **Patch & Release**: If verified, a patch will be prepared and integrated into a new release version of ALOY.
4. **Advisory**: Once fixed, an advisory may be published to inform the community, with attribution to the security researcher if requested.

## 3. Security Best Practices for Users
Because ALOY runs entirely on your local machine, the security of the application relies heavily on your local environment setup. We recommend the following practices:
- **Local SQLite Database Security**: Keep the `data/aloy.db` file secure. Ensure that file system permissions restrict unauthorized users on the same machine from accessing the database directory.
- **Ollama Security Configuration**: Bind Ollama to `127.0.0.1` (localhost) rather than `0.0.0.0` (all interfaces) unless you explicitly require network sharing. This prevents external machines on your local network from accessing your model endpoints or calling model functions.
- **Secure Workspace Folders**: Do not run ALOY in directories containing sensitive keys, passwords, or configuration files that are not meant to be indexed by the local memory engine.
- **Keep Software Updated**: Frequently update your Python runtime, Ollama version, and ALOY releases to benefit from the latest security patches.
