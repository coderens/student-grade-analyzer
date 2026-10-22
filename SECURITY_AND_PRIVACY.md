# GradePilot Security and Privacy Checklist

This checklist is an implementation aid, not a certification of compliance with Republic Act No. 10173 (the Philippine Data Privacy Act of 2012). The school/personal information controller must complete the organizational and legal decisions below before using real student data.

## Application safeguards
- Set a unique, random `SECRET_KEY` in Render; never commit it or share it.
- Set `DATABASE_URL` only in Render's secret environment settings. Use a least-privilege database role where supported.
- Keep `FLASK_DEBUG=false` in production and require HTTPS.
- Keep student account creation approval-gated. Verify identity through a school-approved process before approving an account.
- Review admin access periodically and remove access when roles change.
- Restrict exported CSV/PDF reports to authorized staff; exports contain personal data and must be stored/shared securely.
- Back up the database, test restoration, and define a response plan for suspected incidents.

## School privacy actions required before launch
1. Identify the personal information controller and publish the actual school and DPO/privacy-contact details.
2. Document the purpose and lawful basis for each processing activity; do not assume a registration checkbox automatically makes processing lawful.
3. Confirm what data is necessary, who can access it, the hosting location and provider arrangements, and whether cross-border transfers occur.
4. Set retention and secure-deletion rules for student records, account data, logs, backups, and downloaded reports.
5. Establish processes for data-subject requests, corrections, complaints, access reviews, and incident/breach assessment and notification where required.
6. Train administrators not to share credentials or export files through unauthorized channels.
7. Conduct a privacy/security risk assessment and have the school's responsible privacy/legal personnel review this application before real data is used.

## Known limitations to address in future work
- Add a formal password-reset flow using verified school email or an approved identity provider.
- Add network-level abuse monitoring and security alerting alongside the database-backed per-identifier sign-in throttling.
- Consider MFA for administrator accounts.
- Add automated security tests and dependency scanning in CI.
- Decide whether admin roles should be separated (e.g., records manager vs. account approver) and enforce least privilege.
- Verify privacy notice text and retention policy with the school; the included page has placeholders that must be replaced.
