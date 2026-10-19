"""Events published by the Appointments and Bookings module.

Publishes: appointment.created, appointment.confirmed, appointment.rescheduled, appointment.cancelled,
appointment.no_show, appointment.checked_in, appointment.completed (ids, service, resources, minutes and the
price lines, for billing), appointment.invoiced.
Subscribes to nothing: it reads other units only through their public.py.
"""
