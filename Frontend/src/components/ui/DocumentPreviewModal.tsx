import React, { useState, useEffect, useRef, useCallback } from 'react'
import {
  X,
  ZoomIn,
  ZoomOut,
  RotateCcw,
  Download,
  FileText,
  AlertTriangle,
  RefreshCw,
  Maximize2,
  Minimize2,
  ChevronLeft,
  ChevronRight,
  Sparkles,
} from 'lucide-react'
import * as pdfjsLib from 'pdfjs-dist'
import pdfWorker from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

import { API_BASE_URL } from '../../services/api'
import { useAuthStore } from '../../store/useAuthStore'

// Initialize pdfjs worker
pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorker

export interface DocumentPreviewTarget {
  submissionId: string
  documentIndex: number
  documentName: string
  fileType?: string
  fileName?: string
  studentName?: string
}

interface DocumentPreviewModalProps {
  target: DocumentPreviewTarget | null
  onClose: () => void
}

type LoadState = 'idle' | 'loading' | 'success' | 'error'

const ZOOM_STEP = 0.25
const ZOOM_MIN = 0.5
const ZOOM_MAX = 3.0

function getFileCategory(fileType?: string, fileName?: string): 'pdf' | 'image' | 'unknown' {
  const ext = (fileName?.split('.').pop() || fileType || '').toLowerCase()
  if (ext === 'pdf') return 'pdf'
  if (['jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp', 'svg'].includes(ext)) return 'image'
  if (fileType?.toLowerCase().includes('pdf')) return 'pdf'
  if (
    fileType?.toLowerCase().includes('image') ||
    fileType?.toLowerCase().includes('jpg') ||
    fileType?.toLowerCase().includes('png') ||
    fileType?.toLowerCase().includes('jpeg')
  ) {
    return 'image'
  }
  return 'unknown'
}

interface ErrorDisplayInfo {
  title: string
  desc: string
}

function resolveErrorMessage(statusCode?: number): ErrorDisplayInfo {
  switch (statusCode) {
    case 401:
      return {
        title: 'Unauthorized',
        desc: 'Your session may have expired. Please sign in again.',
      }
    case 403:
      return {
        title: 'Access Denied',
        desc: 'You do not have permission to view this document.',
      }
    case 404:
      return {
        title: 'Document file not found',
        desc: 'The document file could not be found on the server.',
      }
    case 422:
      return {
        title: 'Invalid document request',
        desc: 'The request parameters were invalid.',
      }
    case 500:
      return {
        title: 'Document service error',
        desc: 'An internal service error occurred. Please try again.',
      }
    default:
      return {
        title: 'Unable to connect to document service',
        desc: 'Could not establish connection to the document service. Please check your network.',
      }
  }
}

export const DocumentPreviewModal: React.FC<DocumentPreviewModalProps> = ({ target, onClose }) => {
  const { token } = useAuthStore()
  const [loadState, setLoadState] = useState<LoadState>('idle')
  const [errorInfo, setErrorInfo] = useState<ErrorDisplayInfo>({
    title: 'Unable to preview this document.',
    desc: 'The document file could not be loaded or previewed. Please retry or contact the administrator.',
  })
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const [zoom, setZoom] = useState(1.0)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [retryCount, setRetryCount] = useState(0)

  // PDF-specific states
  const [pdfDoc, setPdfDoc] = useState<pdfjsLib.PDFDocumentProxy | null>(null)
  const [pageNum, setPageNum] = useState(1)
  const [numPages, setNumPages] = useState(1)
  const [useNativePdf, setUseNativePdf] = useState(false)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const renderTaskRef = useRef<any>(null)

  // Image pan states
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [isDragging, setIsDragging] = useState(false)
  const dragOriginRef = useRef({ x: 0, y: 0 })

  // Blob cleanup reference
  const blobRef = useRef<string | null>(null)

  const revokePrevBlob = useCallback(() => {
    if (blobRef.current) {
      URL.revokeObjectURL(blobRef.current)
      blobRef.current = null
    }
  }, [])

  // Reset viewport transforms
  const resetTransform = useCallback(() => {
    setZoom(1.0)
    setPan({ x: 0, y: 0 })
  }, [])

  // Fetch document blob and parse PDF if applicable
  useEffect(() => {
    if (!target) return

    let cancelled = false
    revokePrevBlob()
    setBlobUrl(null)
    setPdfDoc(null)
    setPageNum(1)
    setNumPages(1)
    setUseNativePdf(false)
    resetTransform()
    setLoadState('loading')

    const fetchDoc = async () => {
      try {
        const url = `${API_BASE_URL}/student-submissions/${target.submissionId}/documents/${target.documentIndex}/file`
        const res = await fetch(url, {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        })

        if (cancelled) return

        if (!res.ok) {
          setErrorInfo(resolveErrorMessage(res.status))
          setLoadState('error')
          return
        }

        const blob = await res.blob()
        if (cancelled) return

        const objectUrl = URL.createObjectURL(blob)
        blobRef.current = objectUrl
        setBlobUrl(objectUrl)

        const category = getFileCategory(target.fileType, target.fileName)
        if (category === 'pdf') {
          try {
            const arrayBuffer = await blob.arrayBuffer()
            if (cancelled) return
            const loadingTask = pdfjsLib.getDocument({ data: arrayBuffer })
            const doc = await loadingTask.promise
            if (cancelled) return
            setPdfDoc(doc)
            setNumPages(doc.numPages)
            setPageNum(1)
            setLoadState('success')
          } catch {
            // Fallback to native iframe PDF viewer
            if (!cancelled) {
              setUseNativePdf(true)
              setLoadState('success')
            }
          }
        } else {
          setLoadState('success')
        }
      } catch {
        if (!cancelled) {
          setErrorInfo(resolveErrorMessage(undefined))
          setLoadState('error')
        }
      }
    }

    fetchDoc()

    return () => {
      cancelled = true
    }
  }, [target, token, retryCount, revokePrevBlob, resetTransform])

  // Render PDF page to canvas when pdfDoc, pageNum, or zoom changes
  useEffect(() => {
    if (!pdfDoc || useNativePdf) return

    let isSubscribed = true

    const renderPage = async () => {
      try {
        const page = await pdfDoc.getPage(pageNum)
        if (!isSubscribed) return

        const canvas = canvasRef.current
        if (!canvas) return

        // Cancel previous render task if still active
        if (renderTaskRef.current) {
          try {
            renderTaskRef.current.cancel()
          } catch {
            // ignore cancel errors
          }
        }

        const dpr = window.devicePixelRatio || 1
        const viewport = page.getViewport({ scale: zoom * 1.35 })

        canvas.width = Math.floor(viewport.width * dpr)
        canvas.height = Math.floor(viewport.height * dpr)
        canvas.style.width = `${Math.floor(viewport.width)}px`
        canvas.style.height = `${Math.floor(viewport.height)}px`

        const ctx = canvas.getContext('2d', { alpha: false })
        if (!ctx) return
        ctx.scale(dpr, dpr)

        const renderContext = {
          canvasContext: ctx,
          viewport: viewport,
          canvas: canvas,
        }

        const task = page.render(renderContext)
        renderTaskRef.current = task
        await task.promise
      } catch (err: any) {
        if (err?.name !== 'RenderingCancelledException') {
          // Switch to native PDF viewer fallback if canvas rendering fails
          setUseNativePdf(true)
        }
      }
    }

    renderPage()

    return () => {
      isSubscribed = false
      if (renderTaskRef.current) {
        try {
          renderTaskRef.current.cancel()
        } catch {
          // ignore
        }
      }
    }
  }, [pdfDoc, pageNum, zoom, useNativePdf])

  // Cleanup on close
  useEffect(() => {
    if (!target) {
      revokePrevBlob()
      setBlobUrl(null)
      setPdfDoc(null)
      setLoadState('idle')
      resetTransform()
    }
  }, [target, revokePrevBlob, resetTransform])

  // Keyboard shortcut: Escape to close, Left/Right arrows for PDF pages
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
      } else if (pdfDoc && numPages > 1) {
        if (e.key === 'ArrowLeft') {
          setPageNum((p) => Math.max(1, p - 1))
        } else if (e.key === 'ArrowRight') {
          setPageNum((p) => Math.min(numPages, p + 1))
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, pdfDoc, numPages])

  if (!target) return null

  const category = getFileCategory(target.fileType, target.fileName)
  const isPdf = category === 'pdf'
  const isImage = category === 'image'

  const handleDownload = () => {
    if (!blobUrl) return
    const a = document.createElement('a')
    a.href = blobUrl
    a.download =
      target.fileName ||
      `${target.documentName.replace(/\s+/g, '_')}.${(target.fileType || 'pdf').toLowerCase()}`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  }

  const handleRetry = () => {
    setRetryCount((c) => c + 1)
  }

  const handleZoomIn = () => {
    setZoom((z) => Math.min(ZOOM_MAX, +(z + ZOOM_STEP).toFixed(2)))
  }

  const handleZoomOut = () => {
    setZoom((z) => Math.max(ZOOM_MIN, +(z - ZOOM_STEP).toFixed(2)))
  }

  // Mouse pan handlers for images
  const handleMouseDown = (e: React.MouseEvent) => {
    if (zoom <= 1) return
    setIsDragging(true)
    dragOriginRef.current = { x: e.clientX - pan.x, y: e.clientY - pan.y }
  }

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDragging || zoom <= 1) return
    setPan({
      x: e.clientX - dragOriginRef.current.x,
      y: e.clientY - dragOriginRef.current.y,
    })
  }

  const handleMouseUp = () => {
    setIsDragging(false)
  }

  // Display filename: prefer target.fileName, otherwise synthesize clean name
  const displayFileName =
    target.fileName ||
    `${target.documentName.toLowerCase().replace(/\s+/g, '_')}.${isPdf ? 'pdf' : (target.fileType || 'jpg').toLowerCase()}`

  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center p-2 sm:p-4 overflow-hidden"
      role="dialog"
      aria-modal="true"
      aria-label={`Preview: ${target.documentName}`}
    >
      {/* Dimmed backdrop */}
      <div
        className="absolute inset-0 bg-black/80 backdrop-blur-md transition-opacity"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Main viewer modal */}
      <div
        className={`relative z-10 flex flex-col bg-slate-900 border border-slate-800 text-slate-100 shadow-2xl transition-all duration-200 overflow-hidden ${
          isFullscreen
            ? 'fixed inset-0 rounded-none'
            : 'w-full max-w-5xl h-[90vh] rounded-2xl'
        }`}
      >
        {/* ── HEADER ── */}
        <div className="flex items-center justify-between gap-3 px-4 sm:px-6 py-3.5 border-b border-slate-800/80 bg-slate-900/95 shrink-0 select-none">
          {/* Document info */}
          <div className="flex items-center gap-3 min-w-0">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 shrink-0">
              <FileText className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <h3 className="text-sm sm:text-base font-bold text-white truncate">
                  {target.documentName}
                </h3>
                <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                  {target.fileType || (isPdf ? 'PDF' : 'IMAGE')}
                </span>
              </div>
              <div className="flex items-center gap-2 text-xs text-slate-400 font-mono mt-0.5 truncate">
                <span className="truncate">{displayFileName}</span>
                {target.studentName && (
                  <>
                    <span className="text-slate-600">·</span>
                    <span className="text-slate-300 font-sans truncate">{target.studentName}</span>
                  </>
                )}
              </div>
            </div>
          </div>

          {/* Action toolbar */}
          <div className="flex items-center gap-1 sm:gap-2 shrink-0">
            {/* PDF Page Navigation */}
            {loadState === 'success' && isPdf && !useNativePdf && numPages > 1 && (
              <div className="flex items-center bg-slate-800/80 border border-slate-700/80 rounded-lg p-0.5 mr-1 text-xs">
                <button
                  onClick={() => setPageNum((p) => Math.max(1, p - 1))}
                  disabled={pageNum <= 1}
                  className="h-7 w-7 flex items-center justify-center rounded text-slate-300 hover:text-white hover:bg-slate-700 disabled:opacity-30 transition-colors cursor-pointer"
                  title="Previous page"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <span className="px-2 font-mono text-[11px] text-slate-300 whitespace-nowrap">
                  Page {pageNum} of {numPages}
                </span>
                <button
                  onClick={() => setPageNum((p) => Math.min(numPages, p + 1))}
                  disabled={pageNum >= numPages}
                  className="h-7 w-7 flex items-center justify-center rounded text-slate-300 hover:text-white hover:bg-slate-700 disabled:opacity-30 transition-colors cursor-pointer"
                  title="Next page"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            )}

            {/* Zoom Controls (Images and PDF Canvas) */}
            {loadState === 'success' && (!isPdf || !useNativePdf) && (
              <div className="flex items-center bg-slate-800/80 border border-slate-700/80 rounded-lg p-0.5 text-xs">
                <button
                  onClick={handleZoomOut}
                  disabled={zoom <= ZOOM_MIN}
                  className="h-7 w-7 flex items-center justify-center rounded text-slate-300 hover:text-white hover:bg-slate-700 disabled:opacity-30 transition-colors cursor-pointer"
                  title="Zoom Out"
                >
                  <ZoomOut className="h-3.5 w-3.5" />
                </button>
                <span className="w-10 text-center font-mono text-[11px] text-slate-300 select-none">
                  {Math.round(zoom * 100)}%
                </span>
                <button
                  onClick={handleZoomIn}
                  disabled={zoom >= ZOOM_MAX}
                  className="h-7 w-7 flex items-center justify-center rounded text-slate-300 hover:text-white hover:bg-slate-700 disabled:opacity-30 transition-colors cursor-pointer"
                  title="Zoom In"
                >
                  <ZoomIn className="h-3.5 w-3.5" />
                </button>
                <button
                  onClick={resetTransform}
                  className="h-7 w-7 flex items-center justify-center rounded text-slate-300 hover:text-emerald-400 hover:bg-slate-700 transition-colors cursor-pointer"
                  title="Reset Zoom"
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                </button>
              </div>
            )}

            {/* Download Button (Authorized Staff) */}
            {loadState === 'success' && blobUrl && (
              <button
                onClick={handleDownload}
                className="h-8 px-2.5 flex items-center gap-1.5 rounded-lg border border-slate-700/80 bg-slate-800/80 text-slate-200 hover:bg-slate-700 hover:text-white text-xs font-medium transition-colors cursor-pointer"
                title="Download Document"
              >
                <Download className="h-3.5 w-3.5 text-emerald-400" />
                <span className="hidden sm:inline">Download</span>
              </button>
            )}

            {/* Fullscreen Toggle */}
            <button
              onClick={() => setIsFullscreen((f) => !f)}
              className="h-8 w-8 flex items-center justify-center rounded-lg border border-slate-700/80 bg-slate-800/80 text-slate-300 hover:bg-slate-700 hover:text-white transition-colors cursor-pointer"
              title={isFullscreen ? 'Exit Fullscreen' : 'Fullscreen'}
            >
              {isFullscreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
            </button>

            {/* Close Button */}
            <button
              onClick={onClose}
              className="h-8 w-8 flex items-center justify-center rounded-lg border border-slate-700/80 bg-slate-800/80 text-slate-300 hover:bg-rose-500/20 hover:text-rose-400 hover:border-rose-500/40 transition-colors cursor-pointer"
              title="Close Preview"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* ── CONTENT AREA ── */}
        <div className="flex-1 overflow-hidden relative bg-slate-950 flex items-center justify-center select-none">
          {/* Loading state */}
          {loadState === 'loading' && (
            <div className="flex flex-col items-center justify-center gap-3 p-6 text-center">
              <div className="relative">
                <div className="h-12 w-12 rounded-full border-2 border-emerald-500/20 border-t-emerald-500 animate-spin" />
                <div className="absolute inset-0 flex items-center justify-center">
                  <Sparkles className="h-4 w-4 text-emerald-400 animate-pulse" />
                </div>
              </div>
              <div>
                <p className="text-sm font-semibold text-slate-200">Loading document...</p>
                <p className="text-xs text-slate-500 mt-0.5">{target.documentName}</p>
              </div>
            </div>
          )}

          {/* Error state */}
          {loadState === 'error' && (
            <div className="flex flex-col items-center justify-center gap-4 p-8 max-w-sm text-center">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-rose-500/10 border border-rose-500/20 text-rose-400">
                <AlertTriangle className="h-7 w-7" />
              </div>
              <div>
                <h4 className="text-base font-bold text-white">{errorInfo.title}</h4>
                <p className="text-xs text-slate-400 mt-1">
                  {errorInfo.desc}
                </p>
              </div>
              <div className="flex items-center gap-2 pt-2">
                <button
                  onClick={handleRetry}
                  className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white transition-colors cursor-pointer"
                >
                  <RefreshCw className="h-3.5 w-3.5" />
                  Retry
                </button>
                <button
                  onClick={onClose}
                  className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold rounded-lg border border-slate-700 bg-slate-800 text-slate-300 hover:bg-slate-700 transition-colors cursor-pointer"
                >
                  Close
                </button>
              </div>
            </div>
          )}

          {/* PDF Rendering via Canvas (Rich Viewer with Page navigation & Zoom) */}
          {loadState === 'success' && isPdf && !useNativePdf && (
            <div className="w-full h-full overflow-auto flex items-center justify-center p-4">
              <canvas
                ref={canvasRef}
                className="max-w-none shadow-2xl rounded-lg border border-slate-800 transition-all duration-150"
              />
            </div>
          )}

          {/* PDF Native Fallback (Iframe) */}
          {loadState === 'success' && isPdf && useNativePdf && blobUrl && (
            <iframe
              src={`${blobUrl}#toolbar=1&navpanes=1&scrollbar=1`}
              title={target.documentName}
              className="w-full h-full border-0"
            />
          )}

          {/* Image Rendering with Zoom & Pan */}
          {loadState === 'success' && isImage && blobUrl && (
            <div
              className="w-full h-full overflow-hidden flex items-center justify-center p-4"
              onMouseDown={handleMouseDown}
              onMouseMove={handleMouseMove}
              onMouseUp={handleMouseUp}
              onMouseLeave={handleMouseUp}
              style={{
                cursor: zoom > 1 ? (isDragging ? 'grabbing' : 'grab') : 'default',
              }}
            >
              <img
                src={blobUrl}
                alt={target.documentName}
                draggable={false}
                style={{
                  transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
                  transformOrigin: 'center center',
                  transition: isDragging ? 'none' : 'transform 0.15s ease',
                  maxWidth: zoom <= 1 ? '100%' : 'none',
                  maxHeight: zoom <= 1 ? '100%' : 'none',
                  objectFit: 'contain',
                  borderRadius: '6px',
                  boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
                }}
              />
            </div>
          )}

          {/* Fallback for other file categories */}
          {loadState === 'success' && !isPdf && !isImage && blobUrl && (
            <div className="flex flex-col items-center justify-center gap-4 p-8 text-center">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-slate-800 border border-slate-700 text-slate-400">
                <FileText className="h-7 w-7" />
              </div>
              <div>
                <p className="text-sm font-semibold text-white">Preview unavailable for this format.</p>
                <p className="text-xs text-slate-400 mt-1">Download the document to inspect it locally.</p>
              </div>
              <button
                onClick={handleDownload}
                className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white transition-colors cursor-pointer"
              >
                <Download className="h-3.5 w-3.5" />
                Download Document
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
