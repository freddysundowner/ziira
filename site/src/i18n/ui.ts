import type { Lang } from "../content/types";

export interface Ui {
  skip: string; menu: string; signIn: string; getStarted: string; home: string; breadcrumbs: string;
  primaryNav: string; footerNav: string; keepReading: string; faq: string; readMore: string; updated: string; published: string; minRead: string;
  product: string; intelligence: string; company: string; resources: string; legal: string;
  contactSend: string; contactName: string; contactEmail: string; contactMessage: string; contactCompany: string;
  contactNotConfigured: string; contactEmailLine: string; contactPrivacyNote: string; honeypot: string;
  pricingEmpty: string; pricingPlans: string; templateNotice: string; templateTitle: string; guidesIntro: string;
  glossaryIntro: string; notFoundTitle: string; notFoundText: string; ctaCoreTitle: string; ctaCoreText: string; ctaIntelTitle: string; ctaIntelText: string;
  ctaGeneralTitle: string; ctaGeneralText: string; talk: string; seePricing: string; footerNote: string; screenshotNote: string; allGuides: string; sourcesLead: string;
  features: string; theme: string;
  /** Labels for pages that exist only in English (guides, legal) when shown in another language. */
  labels: Record<string, string>;
}

export const ui: Record<Lang, Ui> = {
  en: {
    skip: "Skip to main content", menu: "Menu", signIn: "Sign in", getStarted: "Get started", home: "Home", breadcrumbs: "Breadcrumb",
    primaryNav: "Main", footerNav: "Site", keepReading: "Keep reading", faq: "Frequently asked questions", readMore: "Read more", updated: "Updated", published: "Published", minRead: "min read",
    product: "Product", intelligence: "Intelligence", company: "Company", resources: "Resources", legal: "Legal",
    contactSend: "Send message", contactName: "Your name", contactEmail: "Email address", contactMessage: "What would you like to know?", contactCompany: "Business name (optional)",
    contactNotConfigured: "The contact form is not switched on yet.", contactEmailLine: "You can reach us at", contactPrivacyNote: "We use what you send only to reply to you.", honeypot: "Leave this field empty",
    pricingEmpty: "Plans and prices are not published yet. Tell us about your business and we will reply with what fits.", pricingPlans: "Plans",
    templateNotice: "Template: not legal advice", templateTitle: "This page is a template",
    guidesIntro: "Practical guides for owners and managers: catching leaks, reconciling money and running branches.",
    glossaryIntro: "Plain-language definitions of the terms used across Ziira and in the guides.", notFoundTitle: "Page not found", notFoundText: "That page does not exist or has moved. Try one of these instead.",
    ctaCoreTitle: "See Ziira on your own business", ctaCoreText: "Create a business in a few minutes and look around with your own products and branches.",
    ctaIntelTitle: "Add daily checking to the system you already use", ctaIntelText: "Keep your current system, let Ziira look at it, and get a daily check of what needs attention.",
    ctaGeneralTitle: "Start with what you need today", ctaGeneralText: "Choose the whole business system, or only the daily checking, when you create your business.",
    talk: "Talk to us", seePricing: "Plans and pricing", footerNote: "Ziira: simplify, connect, grow.", screenshotNote: "Screenshot of the Ziira web app with demo data.", allGuides: "All guides", sourcesLead: "Supported sources",
    features: "Features", theme: "Theme",
    labels: {},
  },
};
