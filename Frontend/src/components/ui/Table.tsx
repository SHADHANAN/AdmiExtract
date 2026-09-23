import React from 'react'

export const Table: React.FC<React.TableHTMLAttributes<HTMLTableElement>> = ({ className = '', children, ...props }) => (
  <div className="w-full overflow-x-auto rounded-xl border border-border bg-card shadow-xs">
    <table className={`w-full caption-bottom text-sm border-collapse ${className}`} {...props}>
      {children}
    </table>
  </div>
)

export const TableHeader: React.FC<React.HTMLAttributes<HTMLTableSectionElement>> = ({ className = '', ...props }) => (
  <thead className={`sticky top-0 z-10 bg-secondary/60 border-b border-border text-muted-foreground ${className}`} {...props} />
)

export const TableBody: React.FC<React.HTMLAttributes<HTMLTableSectionElement>> = ({ className = '', ...props }) => (
  <tbody className={`divide-y divide-border/60 bg-card ${className}`} {...props} />
)

export const TableRow: React.FC<React.HTMLAttributes<HTMLTableRowElement>> = ({ className = '', ...props }) => (
  <tr className={`transition-colors duration-150 hover:bg-secondary/60 ${className}`} {...props} />
)

export const TableHead: React.FC<React.ThHTMLAttributes<HTMLTableCellElement>> = ({ className = '', ...props }) => (
  <th className={`h-11 px-4 text-left align-middle font-semibold text-muted-foreground uppercase tracking-wider text-[11px] select-none [&:has([role=checkbox])]:pr-0 ${className}`} {...props} />
)

export const TableCell: React.FC<React.TdHTMLAttributes<HTMLTableCellElement>> = ({ className = '', ...props }) => (
  <td className={`px-4 py-3.5 align-middle text-sm text-foreground [&:has([role=checkbox])]:pr-0 ${className}`} {...props} />
)
