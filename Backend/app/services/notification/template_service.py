from typing import Dict, Any, Optional
from app.models.verification_notification import NotificationChannel
from app.core.config import settings


DEFAULT_EMAIL_SUBJECT = "Action Required: Verify Your Extracted Admission Data"

DEFAULT_EMAIL_TEMPLATE = """Dear {{student_name}},

Your extracted admission document data for {{batch_name}} is ready for verification.

Please review and confirm or correct your extracted information using the secure verification portal below:

{{verification_link}}

Important Instructions:
1. This link is personal to your registration ({{register_number}}) and should not be shared.
2. Please verify all extracted fields such as your Name, Date of Birth, Gender, and Community.
3. If any field requires correction, you may submit the updated value directly through the portal for staff review.

Regards,
{{institution_name}}"""

DEFAULT_SMS_TEMPLATE = """Admissions Alert: Dear {{student_name}}, your admission data is ready for verification. Please review and confirm your details here: {{verification_link}} - {{institution_name}}"""

DEFAULT_WHATSAPP_TEMPLATE = """*Admission Document Verification*

Hello *{{student_name}}*,

Your document data for *{{batch_name}}* has been processed by our admissions team.

Please verify and confirm your extracted information using the secure link:
{{verification_link}}

_This is a private student verification link. If you notice any discrepancy, submit your corrections directly in the portal._

Regards,
*{{institution_name}}*"""


class NotificationTemplateService:
    """
    Renders personalized, institution-branded notification messages
    without hardcoding specific institutional identities.
    """

    def render(
        self,
        channel: NotificationChannel,
        student_name: str,
        verification_link: str,
        batch_name: Optional[str] = None,
        register_number: Optional[str] = None,
        institution_name: Optional[str] = None,
        custom_subject: Optional[str] = None,
        custom_body: Optional[str] = None,
    ) -> Dict[str, str]:
        eff_institution = institution_name or settings.INSTITUTION_NAME or "Admissions Office"
        eff_batch = batch_name or "Admission Cohort"
        eff_reg = register_number or "Candidate"

        replacements = {
            "{{student_name}}": student_name,
            "{{verification_link}}": verification_link,
            "{{institution_name}}": eff_institution,
            "{{batch_name}}": eff_batch,
            "{{register_number}}": eff_reg,
        }

        if channel == NotificationChannel.EMAIL:
            subject = custom_subject or DEFAULT_EMAIL_SUBJECT
            body = custom_body or DEFAULT_EMAIL_TEMPLATE
        elif channel == NotificationChannel.SMS:
            subject = "SMS Notification"
            body = custom_body or DEFAULT_SMS_TEMPLATE
        else:  # WHATSAPP
            subject = "WhatsApp Notification"
            body = custom_body or DEFAULT_WHATSAPP_TEMPLATE

        for key, val in replacements.items():
            subject = subject.replace(key, str(val))
            body = body.replace(key, str(val))

        return {
            "subject": subject,
            "body": body,
        }
