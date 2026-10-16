import type { HelpGuide } from "./types";

export const support: HelpGuide[] = [
  {
    slug: "fix-common-problems", journey: "support", minutes: 8,
    title: "Fix Common Problems in Ziira: Sign-In, Missing Items",
    description: "Quick fixes for the problems people hit most: cannot sign in, a menu item or product missing, a till that will not sell, a button that is greyed out.",
    h1: "Fix common problems",
    who: "Everyone", time: "About 8 minutes",
    keywords: ["troubleshooting", "problem", "error", "cannot sign in", "forgot password", "missing", "greyed out", "help"],
    need: [],
    steps: [
      { do: "Cannot sign in? Check your email or phone and password. Click **Forgot password?** on the sign-in page and follow the link we email you.", result: "A one-use link to choose a new password.", shot: { key: "fix-1-signin", alt: "The Ziira sign-in page with the Forgot password link under the password box", legend: ["Forgot password?"] } },
      { do: "Told to wait? You typed a wrong password several times. Wait a few minutes and try again, or click **Forgot password?**." },
      { do: "A menu item is missing? Click **Add-ons** to check that part is on. If it is, ask the owner to check your role under **Settings > Users**." },
      { do: "A button is greyed out? A required box is empty, or you are not allowed. Read the message at the top of the form." },
      { do: "A product is not at the till? Open it under **Stock > Products**. Check it is **Active**, has a current price on its **Prices** tab and has the **Stock** type." },
      { do: "A number looks wrong? Look at **Stock > Stock movements** for stock, **Sell > Sales** for sales, or **Money > Accounting** for the books." },
      { do: "No connection? At the till, keep selling: see [Sell offline](@help-sell-offline). Other screens need the internet." },
      { do: "Still stuck? Note the screen, what you clicked and the message, then see [Get help from the Ziira team](@help-contact-ziira)." },
    ],
    problems: [
      { p: "The two-step code is rejected", fix: "Check your phone's clock is right and use the newest code, or use a backup code." },
      { p: "I changed something by mistake", fix: "Recorded sales, stock and entries are not edited. Correct them with a return, an adjustment or a reversal, and give the reason." },
      { p: "I see too much or too little", fix: "Your role decides what you see. Ask the owner to change it." },
    ],
    tips: [],
    next: ["contact-ziira"],
  },
  {
    slug: "contact-ziira", journey: "support", minutes: 5,
    title: "Get Help From the Ziira Team and Share Access Safely",
    description: "How to reach us, what to write so we can help quickly, and how to let Ziira support look at your business for a limited time without sharing a password.",
    h1: "Get help from the Ziira team",
    who: "Everyone", time: "About 5 minutes",
    keywords: ["contact", "support", "help desk", "support access", "email us", "talk to us"],
    need: [],
    steps: [
      { do: "Open the [contact page](@get-started) on this website and use the form or the email address shown there." },
      { do: "Write what you were doing, what you expected, what happened and the exact message on the screen. Say which business and branch.", result: "We can find the problem without a long back and forth." },
      { do: "If we ask to look inside your business, the owner clicks **Settings > Support access**, then **Give support access**. Say why, what they can do and for how long, then click **Give access**.", result: "Support can come in only until the end time you chose.", shot: { key: "support-1-access", alt: "The Support access page explaining that Ziira staff cannot see your data unless you give access, with the Give support access button", legend: ["Give support access"] } },
      { do: "To stop it sooner, click **End access** on the same page.", note: "Everything our staff do is written to your own record. They never sign in as you." },
    ],
    problems: [
      { p: "I did not get a reply", fix: "Check your spam folder, and that you typed your email correctly in the form." },
      { p: "Someone asked for my password", fix: "Never share your password or codes, even with people who say they are from Ziira. Use **Support access** instead." },
      { p: "I want my data removed", fix: "Click **Settings > Privacy** to record and answer a privacy request. Backups may still hold erased data for a time." },
    ],
    tips: [],
    next: ["fix-common-problems"],
  },
];
