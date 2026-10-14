import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  FileSpreadsheet,
  Search,
  Layers,
  Database,
  Users,
  ArrowRight,
  RefreshCw,
  FolderOpen,
} from 'lucide-react';
import { dataExtractionService } from '../services/dataExtractionService';
import type { BatchExtractionStats } from '../types/dataExtraction';
import { useToastStore } from '../store/useToastStore';

export const DataExtraction: React.FC = () => {
  const navigate = useNavigate();
  const { addToast } = useToastStore();

  const [batches, setBatches] = useState<BatchExtractionStats[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedDept, setSelectedDept] = useState('ALL');

  const fetchBatches = async () => {
    try {
      setLoading(true);
      const data = await dataExtractionService.listAuthorizedBatches();
      setBatches(data);
    } catch (err: any) {
      addToast(err?.response?.data?.detail || 'Failed to load authorized batches', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchBatches();
  }, []);

  const departments = Array.from(new Set(batches.map((b) => b.department_id).filter(Boolean)));

  const filteredBatches = batches.filter((b) => {
    const matchesSearch =
      b.batch_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      b.academic_year.toLowerCase().includes(searchQuery.toLowerCase()) ||
      b.department_id.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesDept = selectedDept === 'ALL' || b.department_id === selectedDept;
    return matchesSearch && matchesDept;
  });

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl sm:text-3xl font-extrabold tracking-tight text-foreground flex items-center gap-2.5">
              <span className="p-2 rounded-xl bg-primary/10 text-primary border border-primary/20">
                <FileSpreadsheet className="h-6 w-6" />
              </span>
              DATA EXTRACTION
            </h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
              Active Platform
            </span>
          </div>
          <p className="text-sm text-muted-foreground mt-1">
            On-demand student document intelligence • Stored once, extracted when needed
          </p>
        </div>

        <button
          onClick={fetchBatches}
          className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-semibold rounded-lg border border-border bg-card hover:bg-muted text-foreground transition-all cursor-pointer shadow-xs self-start"
          title="Refresh batch list"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Filter Bar */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 bg-card p-3 rounded-xl border border-border shadow-xs">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <input
            type="text"
            placeholder="Search admission batches by name, year, or department..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-4 py-2 text-sm bg-background rounded-lg border border-input focus:outline-hidden focus:ring-2 focus:ring-primary focus:border-transparent text-foreground placeholder:text-muted-foreground transition-all"
          />
        </div>

        {departments.length > 1 && (
          <div className="flex items-center gap-2 shrink-0">
            <span className="text-xs font-semibold text-muted-foreground uppercase">Department:</span>
            <select
              value={selectedDept}
              onChange={(e) => setSelectedDept(e.target.value)}
              className="px-3 py-2 text-xs font-semibold bg-background rounded-lg border border-input focus:outline-hidden focus:ring-2 focus:ring-primary text-foreground cursor-pointer"
            >
              <option value="ALL">All Departments</option>
              {departments.map((dept) => (
                <option key={dept} value={dept}>
                  {dept}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* Batches Grid */}
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-64 rounded-2xl bg-card border border-border animate-pulse p-6 space-y-4"
            >
              <div className="h-6 w-3/4 bg-muted rounded-md" />
              <div className="h-4 w-1/2 bg-muted rounded-md" />
              <div className="grid grid-cols-2 gap-3 pt-4">
                <div className="h-16 bg-muted rounded-xl" />
                <div className="h-16 bg-muted rounded-xl" />
              </div>
            </div>
          ))}
        </div>
      ) : filteredBatches.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-border bg-card/50 p-12 text-center space-y-3">
          <div className="h-12 w-12 rounded-full bg-muted flex items-center justify-center mx-auto text-muted-foreground">
            <FolderOpen className="h-6 w-6" />
          </div>
          <h3 className="text-base font-bold text-foreground">No Authorized Admission Batches Found</h3>
          <p className="text-xs text-muted-foreground max-w-md mx-auto">
            {searchQuery
              ? 'No batches match your search criteria. Try clearing the filter.'
              : 'You do not have access to any admission batches yet, or none have been created for your department.'}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {filteredBatches.map((batch) => {
            const hasExtractions = batch.extractions_count > 0;
            const latest = batch.latest_extraction;

            return (
              <div
                key={batch.batch_id}
                className="group relative flex flex-col justify-between rounded-2xl border border-border bg-card p-5 shadow-xs hover:shadow-md hover:border-primary/40 transition-all duration-200"
              >
                <div className="space-y-4">
                  {/* Top Bar: Dept + Academic Year */}
                  <div className="flex items-center justify-between">
                    <span className="px-2.5 py-0.5 rounded-full text-xs font-bold tracking-wider uppercase bg-primary/10 text-primary border border-primary/20">
                      {batch.department_id || 'GENERAL'}
                    </span>
                    <span className="text-xs font-semibold text-muted-foreground">
                      {batch.academic_year}
                    </span>
                  </div>

                  {/* Batch Title */}
                  <div>
                    <h3 className="text-lg font-extrabold text-foreground group-hover:text-primary transition-colors">
                      {batch.batch_name}
                    </h3>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      Batch Identifier: <code className="text-[11px] font-mono">{batch.batch_id}</code>
                    </p>
                  </div>

                  {/* Stats Badges */}
                  <div className="grid grid-cols-2 gap-2.5 pt-1">
                    <div className="flex items-center gap-2.5 p-2.5 rounded-xl bg-muted/40 border border-border/60">
                      <div className="p-1.5 rounded-lg bg-blue-500/10 text-blue-500 shrink-0">
                        <Users className="h-4 w-4" />
                      </div>
                      <div className="min-w-0">
                        <div className="text-[10px] uppercase font-bold text-muted-foreground tracking-wider">
                          Students
                        </div>
                        <div className="text-sm font-black text-foreground">
                          {batch.students_count}
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-2.5 p-2.5 rounded-xl bg-muted/40 border border-border/60">
                      <div className="p-1.5 rounded-lg bg-emerald-500/10 text-emerald-500 shrink-0">
                        <Database className="h-4 w-4" />
                      </div>
                      <div className="min-w-0">
                        <div className="text-[10px] uppercase font-bold text-muted-foreground tracking-wider">
                          Stored Docs
                        </div>
                        <div className="text-sm font-black text-foreground">
                          {batch.stored_documents_count}
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Extraction History Status */}
                  <div className="p-3 rounded-xl bg-background border border-border/80 space-y-1.5 text-xs">
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-muted-foreground flex items-center gap-1.5">
                        <Layers className="h-3.5 w-3.5 text-primary" />
                        Previous Extractions:
                      </span>
                      <span className="font-bold text-foreground">
                        {batch.extractions_count} requests
                      </span>
                    </div>

                    {hasExtractions && latest ? (
                      <div className="pt-1.5 border-t border-border/60 flex items-center justify-between text-[11px]">
                        <span className="text-muted-foreground truncate">
                          Latest: {latest.requested_fields.length} fields
                        </span>
                        <span
                          className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${
                            latest.status === 'COMPLETED' || latest.status === 'VERIFIED'
                              ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
                              : latest.status === 'PROCESSING'
                              ? 'bg-amber-500/10 text-amber-600 dark:text-amber-400'
                              : 'bg-slate-500/10 text-slate-500'
                          }`}
                        >
                          {latest.status}
                        </span>
                      </div>
                    ) : (
                      <div className="text-[11px] text-muted-foreground italic pt-1 border-t border-border/60">
                        No extractions yet. Ready to extract.
                      </div>
                    )}
                  </div>
                </div>

                {/* Card Actions */}
                <div className="mt-5 pt-3 border-t border-border flex items-center gap-2">
                  <button
                    onClick={() => navigate(`/data-extraction/${batch.batch_id}`)}
                    className="flex-1 inline-flex items-center justify-center gap-2 px-3.5 py-2.5 rounded-xl bg-primary hover:bg-primary/90 text-primary-foreground text-xs font-bold shadow-xs hover:shadow-sm transition-all cursor-pointer"
                  >
                    <span>Open Batch Workspace</span>
                    <ArrowRight className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
