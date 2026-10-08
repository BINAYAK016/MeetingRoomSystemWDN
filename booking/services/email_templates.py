"""Shared, escaped HTML for company email; the caller also supplies plain text."""

from django.conf import settings
from django.template.loader import render_to_string
from django.urls import reverse

EMAIL_LOGO_CID = "transgate-wordmark@meeting-rooms"


def public_url(route, *args):
    return settings.PUBLIC_BASE_URL.rstrip("/") + reverse(route, args=args)


def render_email(
    *,
    heading,
    intro,
    status="",
    tone="navy",
    preheader="",
    metadata=(),
    paragraphs=(),
    action_url="",
    action_label="View meeting",
    checkin_url="",
    checkin_window="",
    checkin_notice="",
    notice="",
    code="",
    security_note="",
):
    colors = {
        "navy": ("#edf3f9", "#153e64"),
        "green": ("#e7f5ee", "#17633e"),
        "amber": ("#fff4db", "#805617"),
        "red": ("#fff0f1", "#a92335"),
    }
    badge_background, badge_color = colors.get(tone, colors["navy"])
    return render_to_string(
        "booking/email/message.html",
        {
            "logo_cid": EMAIL_LOGO_CID,
            "app_url": public_url("home"),
            "heading": heading,
            "intro": intro,
            "status": status,
            "preheader": preheader or intro,
            "badge_background": badge_background,
            "badge_color": badge_color,
            "metadata": metadata,
            "paragraphs": paragraphs,
            "action_url": action_url,
            "action_label": action_label,
            "checkin_url": checkin_url,
            "checkin_window": checkin_window,
            "checkin_notice": checkin_notice,
            "notice": notice,
            "code": code,
            "security_note": security_note,
        },
    )


def login_email_html(link):
    return render_email(
        heading="Your meeting space awaits.",
        intro="Sign in to Meeting Rooms to reserve a space and see the meetings you organize or attend.",
        status="Employee sign-in",
        action_url=link,
        action_label="Sign in to Meeting Rooms",
        notice="This secure link works once and expires in 15 minutes.",
        security_note="If you did not request this email, you can ignore it. Do not forward your sign-in link.",
    )


def staff_code_email_html(code):
    return render_email(
        heading="One more step to your staff desk.",
        intro="Enter this one-time code on the staff sign-in page to complete your sign-in.",
        status="Staff verification",
        code=code,
        notice="Your code expires in 10 minutes and can be used once.",
        security_note="Keep this code private. If you did not request it, contact your IT team.",
    )


def staff_setup_email_html(link):
    return render_email(
        heading="Welcome to the staff desk.",
        intro="Your staff access is ready. Set your password to manage meeting rooms, requests and bookings.",
        status="Staff access",
        action_url=link,
        action_label="Set your staff password",
        notice="Staff sign-in uses your password followed by a one-time code sent to your company email.",
        security_note="If you did not expect this invitation, contact IT. Do not share this password setup link.",
    )
