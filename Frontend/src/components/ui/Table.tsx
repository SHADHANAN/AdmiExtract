import React from 'react'

export const Table: React.FC<React.TableHTMLAttributes<HTMLTableElement>> = ({ className = '', children, ...props }) => (
  <div className="w-full overflow-auto rounded-lg border border-border bg-card">
    <table className={`w-full caption-bottom text-sm ${className}`} {...props}>
      {children}
    </table>
  </div>
)

export const TableHeader: React.FC<React.HTMLAttributes<HTMLTableSectionElement>> = ({ className = '', ...props }) => (
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
)
