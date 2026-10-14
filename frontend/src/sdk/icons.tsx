/** Icons modules may name in their menu (by string, so a module manifest stays plain data). */
import {
  BadgeDollarSign, BarChart3, Banknote, BookOpen, Boxes, Building2, ClipboardList, CreditCard, FileText, Home, Landmark, LayoutDashboard,
  type LucideIcon, Package, Receipt, Settings, ShieldCheck, ShoppingCart, Sparkles, Truck, Users, UserCog, Wallet, Warehouse,
} from "lucide-react";

export const ICONS: Record<string, LucideIcon> = {
  home: Home, dashboard: LayoutDashboard, products: Package, stock: Warehouse, boxes: Boxes, sales: ShoppingCart, receipt: Receipt, customers: Users,
  suppliers: Truck, purchases: ClipboardList, finance: Landmark, ledger: BookOpen, reports: BarChart3, expenses: Wallet, payments: CreditCard,
  cash: Banknote, people: UserCog, payroll: BadgeDollarSign, company: Building2, settings: Settings, security: ShieldCheck, document: FileText, spark: Sparkles,
};

export function iconFor(name: string | undefined): LucideIcon {
  return (name && ICONS[name]) || FileText;
}
