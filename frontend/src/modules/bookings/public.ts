/** What other modules may use from Bookings: the shared calendar, and links to its pages. */

export { Calendar, Legend, type CalendarProps } from "./components/Calendar";

/** The page of today's arrivals at the front desk. */
export const FRONT_DESK_PATH = "/front-desk";

/** The calendar page. */
export const CALENDAR_PATH = "/calendar";

/** The public address of a business's booking page, for links and QR codes. */
export const bookingPageUrl = (slug: string): string => `${window.location.origin}/book/${slug}`;
