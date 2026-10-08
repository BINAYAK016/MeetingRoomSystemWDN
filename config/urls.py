from django.urls import path

from booking import booking_views, error_views, profile_views, staff_views, views
from booking.health import liveness, readiness
from booking.room_media import room_photo

handler400 = error_views.bad_request
handler403 = error_views.permission_denied
handler404 = error_views.not_found
handler500 = error_views.server_error


urlpatterns = [
    path("", views.home, name="home"),
    path("sign-in/", views.sign_in, name="sign-in"),
    path("sign-in/link/<str:token>/", views.login_link, name="login-link"),
    path("sign-in/confirm/", views.login_confirm, name="login-confirm"),
    path("sign-out/", views.sign_out, name="sign-out"),
    path("profile/", profile_views.profile, name="profile"),
    path("dev/mail/", views.dev_mail, name="dev-mail"),
    path("rooms/", booking_views.room_list, name="rooms"),
    path("rooms/<int:room_id>/", booking_views.room_detail, name="room-detail"),
    path("rooms/<int:room_id>/photo/", room_photo, name="room-photo"),
    path("calendar/", booking_views.calendar_view, name="calendar"),
    path("bookings/new/", booking_views.booking_new, name="booking-new"),
    path("bookings/availability/", booking_views.booking_availability, name="booking-availability"),
    path("bookings/attendees/suggestions/", booking_views.attendee_suggestions, name="attendee-suggestions"),
    path("bookings/mine/", booking_views.my_bookings, name="my-bookings"),
    path("bookings/<int:booking_id>/", booking_views.booking_detail, name="booking-detail"),
    path("bookings/<int:booking_id>/edit/", booking_views.booking_edit, name="booking-edit"),
    path("bookings/<int:booking_id>/cancel/", booking_views.booking_cancel, name="booking-cancel"),
    path("check-in/link/<str:token>/", booking_views.checkin_link, name="checkin-link"),
    path("check-in/confirm/", booking_views.checkin_confirm, name="checkin-confirm"),
    path("staff/sign-in/", staff_views.staff_login, name="staff-login"),
    path("staff/code/", staff_views.staff_code, name="staff-code"),
    path(
        "staff/set-password/<str:uid>/<str:token>/", staff_views.set_staff_password, name="staff-set-password"
    ),
    path("staff/", staff_views.dashboard, name="staff-dashboard"),
    path("staff/rooms/", staff_views.rooms, name="staff-rooms"),
    path("staff/rooms/new/", staff_views.room_form, name="staff-room-new"),
    path("staff/rooms/<int:room_id>/", staff_views.room_form, name="staff-room-edit"),
    path("staff/rooms/<int:room_id>/approval/", staff_views.room_approval, name="staff-room-approval"),
    path("staff/bookings/", staff_views.bookings, name="staff-bookings"),
    path(
        "staff/bookings/pending/",
        staff_views.bookings,
        {"pending_only": True},
        name="staff-bookings-pending",
    ),
    path(
        "staff/bookings/<int:booking_id>/approve/", staff_views.booking_approve, name="staff-booking-approve"
    ),
    path("staff/bookings/<int:booking_id>/reject/", staff_views.booking_reject, name="staff-booking-reject"),
    path("staff/bookings/<int:booking_id>/check-in/", staff_views.staff_checkin, name="staff-checkin"),
    path("staff/blocks/", staff_views.blocks, name="staff-blocks"),
    path("staff/blocks/new/", staff_views.block_new, name="staff-block-new"),
    path("staff/blocks/<int:block_id>/cancel/", staff_views.block_cancel, name="staff-block-cancel"),
    path("staff/policy/", staff_views.policy, name="staff-policy"),
    path("staff/holidays/", staff_views.holidays, name="staff-holidays"),
    path("staff/holidays/<int:holiday_id>/delete/", staff_views.holiday_delete, name="staff-holiday-delete"),
    path("staff/users/", staff_views.users, name="staff-users"),
    path("staff/users/save/", staff_views.user_save, name="staff-user-save"),
    path("staff/users/<int:user_id>/setup/", staff_views.send_staff_setup, name="staff-user-setup"),
    path("staff/reports/", staff_views.reports, name="staff-reports"),
    path("staff/reports.xlsx", staff_views.report_excel, name="staff-report-excel"),
    path("staff/audit/", staff_views.audit, name="staff-audit"),
    path("healthz/", readiness, name="healthcheck"),
    path("livez/", liveness, name="liveness"),
]
