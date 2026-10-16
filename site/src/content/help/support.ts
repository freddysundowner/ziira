import type { HelpGuide } from "./types";

export const support: HelpGuide[] = [
  {
    slug: "fix-common-problems", journey: "support", minutes: 8,
    title: "Fix Common Problems in Ziira: Sign-In, Missing Items",
    description: "Quick fixes for the problems people hit most: cannot sign in, a menu item or product missing, a till that will not sell, a button that is greyed out.",
    h1: "Fix common problems",
    who: "Everyone", time: "About 8 minutes",
    keywords: ["troubleshooting", "problem", "error", "cannot sign in", "forgot password", "missing", "greyed out", "help"],
    need: ["Your sign-in details.", "The name of the screen where it goes wrong."],
    steps: [
      { do: "Cannot sign in? Check you typed your email or phone and password exactly. Click **Forgot password?** on the sign-in page and follow the emailed link.", result: "A one-use link that lets you choose a new password.", shot: { key: "fix-1-signin", alt: "The Ziira sign-in page with the Forgot password link under the password box", legend: ["Forgot password?"] } },
      { do: "If you are told to wait, you typed the wrong password several times. Ziira pauses sign-in for a while. Wait and try again, or use **Forgot password?**." },
      { do: "A menu item or page is missing? Open **Add-ons** to check the part is switched on, then ask the owner to check your role under **Settings > Users**." },
      { do: "A button is greyed out? A required box is empty (look for the red star), or you are not allowed. Hover or read the message at the top of the form." },
      { do: "A product is not at the till? Open it from **Stock > Products** and check it is **Active**, has a current price on its **Prices** tab and is a stock product." },
      { do: "A number looks wrong? Open **Stock > Stock movements** for stock, **Sell > Sales** for sales or **Money > Accounting** for the books to see the records behind it." },
      { do: "The page will not load, or the connection is lost? Refresh. At the till, keep selling: see [Sell offline](@help-sell-offline). Other screens need the internet." },
      { do: "Still stuck? Write down the screen, what you clicked and the message shown, then contact us: see [Get help from the Ziira team](@help-contact-ziira)." },
    ],
    problems: [
      { p: "Two-step code is rejected", fix: "Check your phone's clock is correct and use the newest code, or use a backup code." },
      { p: "I changed something by mistake", fix: "Posted records are not edited in Ziira. Correct them with a reversal, return or adjustment, and give the reason." },
      { p: "I see someone else's branch", fix: "Roles decide what a person sees. If you see too much or too little, ask the owner to change your role." },
    ],
    tips: ["Read error messages: most say exactly what to fix.", "Look up unfamiliar words in the [glossary](@glossary)."],
    next: ["contact-ziira", "tour-of-the-screens", "roles-and-security"],
  },
  {
    slug: "contact-ziira", journey: "support", minutes: 5,
    title: "Get Help From the Ziira Team and Share Access Safely",
    description: "How to reach us, what to write so we can help quickly, and how to let Ziira support look at your business for a limited time without sharing a password.",
    h1: "Get help from the Ziira team",
    who: "Everyone", time: "About 5 minutes",
    keywords: ["contact", "support", "help desk", "support access", "email us", "talk to us"],
    need: ["A short description of the problem, the screen it happened on and the time."],
    steps: [
      { do: "Open the [contact page](@get-started) on this website and use the form, or the email address shown there.", note: "If no contact form is shown yet, the page says so and gives another way to reach us." },
      { do: "Write what you were doing, what you expected, what happened and the exact message on the screen. Say which business and which branch.", result: "Enough for us to find the problem without a long back and forth." },
      { do: "If we ask to look inside your business, the owner opens **Settings > Support access** and clicks **Give support access**.", result: "You choose a reason, a level and an end time. Nothing is open unless you open it.", shot: { key: "support-1-access", alt: "The Support access page explaining that Ziira staff cannot see your data unless you give access, with the Give support access button", legend: ["Give support access"] } },
      { do: "When we are finished, end the access at any time from the same page.", note: "Everything our staff do while they are in is written to your own audit log, and Ziira staff never sign in as you." },
    ],
    problems: [
      { p: "I did not get a reply", fix: "Check your spam folder for our reply and that you typed your email correctly in the form." },
      { p: "Someone asked for my password", fix: "Never share your password or codes with anyone, including people who say they are from Ziira. Use **Support access** instead." },
      { p: "I want my data removed", fix: "Open **Settings > Privacy** to handle a privacy request. Backups may still hold erased data for a time." },
    ],
    tips: ["A screenshot of the problem helps. Hide anything private first.", "Ziira is being prepared for its first pilot businesses. If something is not working, we want to know."],
    next: ["fix-common-problems", "roles-and-security", "tour-of-the-screens"],
  },
];
