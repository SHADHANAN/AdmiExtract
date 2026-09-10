import React from 'react'

export const Table: React.FC<React.TableHTMLAttributes<HTMLTableElement>> = ({ className = '', children, ...props }) => (
<<<<<<< HEAD
  <div className="w-full overflow-x-auto rounded-2xl border border-white/[0.08] bg-[#111827] shadow-[0_4px_24px_rgba(0,0,0,0.35)]">
    <table className={`w-full caption-bottom text-sm border-collapse ${className}`} {...props}>
=======
  <div className="w-full overflow-auto rounded-lg border border-border bg-card">
    <table className={`w-full caption-bottom text-sm ${className}`} {...props}>
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
      {children}
    </table>
  </div>
)

export const TableHeader: React.FC<React.HTMLAttributes<HTMLTableSectionElement>> = ({ className = '', ...props }) => (
<<<<<<< HEAD
  <thead className={`sticky top-0 z-10 bg-[#0F172A]/90 backdrop-blur-md border-b border-white/[0.08] ${className}`} {...props} />
)

export const TableBody: React.FC<React.HTMLAttributes<HTMLTableSectionElement>> = ({ className = '', ...props }) => (
  <tbody className={`divide-y divide-white/[0.06] ${className}`} {...props} />
)

export const TableRow: React.FC<React.HTMLAttributes<HTMLTableRowElement>> = ({ className = '', ...props }) => (
  <tr className={`transition-colors duration-150 hover:bg-white/[0.03] ${className}`} {...props} />
)

export const TableHead: React.FC<React.ThHTMLAttributes<HTMLTableCellElement>> = ({ className = '', ...props }) => (
  <th className={`h-11 px-4 text-left align-middle font-semibold text-slate-400 uppercase tracking-wider text-[11px] select-none [&:has([role=checkbox])]:pr-0 ${className}`} {...props} />
)

export const TableCell: React.FC<React.TdHTMLAttributes<HTMLTableCellElement>> = ({ className = '', ...props }) => (
  <td className={`px-4 py-3.5 align-middle text-sm text-white [&:has([role=checkbox])]:pr-0 ${className}`} {...props} />
=======
  <thead className={`bg-secondary/50 border-b border-border ${className}`} {...props} />
)

export const TableBody: React.FC<React.HTMLAttributes<HTMLTableSectionElement>> = ({ className = '', ...props }) => (
  <tbody className={`divide-y divide-border ${className}`} {...props} />
)

export const TableRow: React.FC<React.HTMLAttributes<HTMLTableRowElement>> = ({ className = '', ...props }) => (
  <tr className={`transition-colors hover:bg-muted/50 ${className}`} {...props} />
)

export const TableHead: React.FC<React.ThHTMLAttributes<HTMLTableCellElement>> = ({ className = '', ...props }) => (
  <th className={`h-10 px-4 text-left align-middle font-medium text-muted-foreground uppercase tracking-wider text-xs [&:has([role=checkbox])]:pr-0 ${className}`} {...props} />
)

export const TableCell: React.FC<React.TdHTMLAttributes<HTMLTableCellElement>> = ({ className = '', ...props }) => (
  <td className={`p-4 align-middle [&:has([role=checkbox])]:pr-0 ${className}`} {...props} />
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
)
