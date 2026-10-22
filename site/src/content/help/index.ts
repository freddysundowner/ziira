import type { HelpGuide } from "./types";
import { getStarted } from "./get-started";
import { sell } from "./sell";
import { stock } from "./stock";
import { buy } from "./buy";
import { customers } from "./customers";
import { money } from "./money";
import { people } from "./people";
import { intelligence } from "./intelligence";
import { settings } from "./settings";
import { support } from "./support";
import { firstWeek } from "./first-week";
import { bookings } from "./bookings";
import { jobs } from "./jobs";
import { timeProjects } from "./time-projects";
import { memberships } from "./memberships";
import { files } from "./files";

export const allGuides: HelpGuide[] = [...getStarted, ...firstWeek, ...sell, ...stock, ...buy, ...customers, ...money, ...people, ...bookings, ...jobs, ...timeProjects, ...memberships, ...files, ...intelligence, ...settings, ...support];
