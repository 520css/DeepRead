"use client";

import { useRef, useState, useCallback, useEffect, useMemo, type RefObject } from "react";
import {
	PdfLoader,
	PdfHighlighter,
	PdfHighlighterUtils,
} from "react-pdf-highlighter-extended";
import type {
	PdfSelection,
	GhostHighlight,
	ViewportHighlight,
} from "react-pdf-highlighter-extended";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { fetchFromApi } from "@/lib/api";
import { ChevronUp } from "lucide-react";
import {
	PaperHighlight,
	PaperHighlightAnnotation,
	ScaledPosition,
	HighlightColor,
} from "@/lib/schema";

import EnigmaticLoadingExperience from "@/components/EnigmaticLoadingExperience";
import { PaperStatus } from "./utils/PdfStatus";
import InlineAnnotationMenu from "./InlineAnnotationMenu";
import { AnnotationHoverCard } from "./AnnotationHoverCard";
import { TranslationPopover } from "./TranslationPopover";
import { BasicUser } from "@/lib/auth";

import {
	ExtendedHighlight,
	paperHighlightToExtended,
	extendedToPaperHighlight,
	HighlightContainer,
	activeHighlightStore,
	usePdfSearch,
	PdfToolbar,
	findTextPages,
	createTextHighlightOverlays,
	getAssistantHighlightBackgroundRgba,
	getUserHighlightBackgroundRgba,
	PDF_TEXT_SELECTION_FILL,
} from "./pdf-viewer";

// Re-export types for external use
export type { ExtendedHighlight };
export { paperHighlightToExtended, extendedToPaperHighlight };

// Position data for highlights rendered via DOM overlays (assistant highlights)
export interface RenderedHighlightPosition {
	left: number;
	top: number;
	width: number;
	height: number;
	page: number;
}

/** Matches `w-[280px]` on margin annotation cards */
const ANNOTATION_CARD_WIDTH_PX = 280;
const ANNOTATION_CARD_MARGIN_GAP_PX = 8;

/**
 * Anchor for margin annotation cards: right gutter by default, left gutter if the
 * card would not fit to the right of the page in the scroll container.
 */
function getAnnotationCardAnchorForHighlight(
	highlight: PaperHighlight,
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	viewer: any,
	scrollContainer: HTMLElement
): { top: number; left: number } | null {
	if (!highlight.position || !highlight.page_number) return null;

	const pageView = viewer.getPageView(highlight.page_number - 1);
	if (!pageView?.div || !pageView?.viewport) return null;

	const { div: pageDiv, viewport } = pageView;
	const { boundingRect } = highlight.position;
	const scaleY = viewport.height / boundingRect.height;

	const containerRect = scrollContainer.getBoundingClientRect();
	const pageRect = (pageDiv as HTMLElement).getBoundingClientRect();
	const scrollLeft = scrollContainer.scrollLeft;

	const top =
		pageRect.top -
		containerRect.top +
		scrollContainer.scrollTop +
		boundingRect.y1 * scaleY;

	const pageRightContent = pageRect.right - containerRect.left + scrollLeft;
	const pageLeftContent = pageRect.left - containerRect.left + scrollLeft;

	const rightGutterLeft = pageRightContent + ANNOTATION_CARD_MARGIN_GAP_PX;
	const leftGutterLeft = pageLeftContent - ANNOTATION_CARD_MARGIN_GAP_PX - ANNOTATION_CARD_WIDTH_PX;

	let left = rightGutterLeft;
	if (
		rightGutterLeft + ANNOTATION_CARD_WIDTH_PX > scrollContainer.scrollWidth &&
		leftGutterLeft >= 0
	) {
		left = leftGutterLeft;
	}

	return { top, left };
}

interface PdfHighlighterViewerProps {
	pdfUrl: string;
	explicitSearchTerm?: string;
		jumpToPage?: number | null;
	highlights: PaperHighlight[];
	setHighlights: (highlights: PaperHighlight[]) => void;
	selectedText: string;
	setSelectedText: (text: string) => void;
	tooltipPosition: { x: number; y: number } | null;
	setTooltipPosition: (position: { x: number; y: number } | null) => void;
	isAnnotating: boolean;
	setIsAnnotating: (isAnnotating: boolean) => void;
	isHighlightInteraction: boolean;
	setIsHighlightInteraction: (isHighlightInteraction: boolean) => void;
	activeHighlight: PaperHighlight | null;
	setActiveHighlight: (highlight: PaperHighlight | null) => void;
	addHighlight: (
		selectedText: string,
		position?: ScaledPosition,
		pageNumber?: number,
		doAnnotate?: boolean,
		color?: HighlightColor
	) => void;
	removeHighlight: (highlight: PaperHighlight) => void;
	loadHighlights: () => Promise<void>;
	renderAnnotations: (annotations: PaperHighlightAnnotation[]) => void;
	annotations: PaperHighlightAnnotation[];
	handleStatusChange?: (status: PaperStatus) => void;
	paperStatus?: PaperStatus;
	setUserMessageReferences: React.Dispatch<React.SetStateAction<string[]>>;
	onOverlaysCreated?: (positions: Map<string, RenderedHighlightPosition>) => void;
	onRefreshUrl?: () => Promise<string | null>;
	addAnnotation?: (highlightId: string, content: string) => Promise<PaperHighlightAnnotation>;
	updateAnnotation?: (annotationId: string, content: string) => Promise<unknown> | void;
	removeAnnotation?: (annotationId: string) => void;
	currentUser?: BasicUser | null;
	/** Callback when user clicks Annotate — parent should switch side panel to Annotations */
	onAnnotateRequest?: (highlightId: string) => void;
	/** When true, the side panel is taking horizontal space — left-align PDF pages to make room for margin cards. */
	sidePanelOpen?: boolean;
	/** Focus / read mode state for the PdfToolbar toggle. */
	isReadMode?: boolean;
	onToggleReadMode?: () => void;
}

/** Syncs PdfLoader's render-prop pdfDocument into parent state without calling setState during render. */
function PdfDocumentSync({
	pdfDocument,
	pdfDocumentRef,
	setPdfReady,
	setNumPages,
}: {
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	pdfDocument: any;
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	pdfDocumentRef: RefObject<any>;
	setPdfReady: (ready: boolean) => void;
	setNumPages: (n: number) => void;
}) {
	useEffect(() => {
		pdfDocumentRef.current = pdfDocument;
		setPdfReady(true);
	}, [pdfDocument, pdfDocumentRef, setPdfReady]);

	useEffect(() => {
		setNumPages(pdfDocument.numPages);
	}, [pdfDocument.numPages, setNumPages]);

	return null;
}

export function PdfHighlighterViewer(props: PdfHighlighterViewerProps) {
	const {
		pdfUrl,
		explicitSearchTerm,
			jumpToPage,
		highlights,
		setHighlights,
		selectedText,
		setSelectedText,
		tooltipPosition,
		setTooltipPosition,
		isAnnotating,
		setIsAnnotating,
		isHighlightInteraction,
		setIsHighlightInteraction,
		activeHighlight,
		setActiveHighlight,
		addHighlight,
		removeHighlight,
		paperStatus,
		handleStatusChange = () => { },
		setUserMessageReferences,
		onOverlaysCreated,
		onRefreshUrl,
		addAnnotation,
		updateAnnotation,
		removeAnnotation,
		currentUser,
		annotations,
		onAnnotateRequest,
		sidePanelOpen = false,
		isReadMode = false,
		onToggleReadMode,
	} = props;

	/** Hover card: show annotations on highlight hover when margin cards are hidden */
	const [hoverHighlightId, setHoverHighlightId] = useState<string | null>(null);
	const [hoverPosition, setHoverPosition] = useState<{ x: number; y: number } | null>(null);

	/** Translation popover state */
	const [translationText, setTranslationText] = useState<string | null>(null);
	const [isTranslating, setIsTranslating] = useState(false);
	const [translationPos, setTranslationPos] = useState<{ x: number; y: number } | null>(null);

	// Track the effective PDF URL, which may be refreshed on 403 errors
	const [effectivePdfUrl, setEffectivePdfUrl] = useState(pdfUrl);
	const [isRefreshingUrl, setIsRefreshingUrl] = useState(false);
	const [pdfLoaderKey, setPdfLoaderKey] = useState(0);
	const refreshAttemptRef = useRef(0);
	const MAX_REFRESH_ATTEMPTS = 2;

	// Sync effective URL when parent provides a new pdfUrl
	useEffect(() => {
		setEffectivePdfUrl(pdfUrl);
		refreshAttemptRef.current = 0;
	}, [pdfUrl]);

	// Handle PDF load errors — refresh presigned URL on 403
	const handlePdfError = useCallback(
		async (error: Error) => {
			const is403 = error.message?.includes("403");
			if (
				is403 &&
				onRefreshUrl &&
				refreshAttemptRef.current < MAX_REFRESH_ATTEMPTS &&
				!isRefreshingUrl
			) {
				refreshAttemptRef.current += 1;
				setIsRefreshingUrl(true);
				try {
					const freshUrl = await onRefreshUrl();
					if (freshUrl) {
						setEffectivePdfUrl(freshUrl);
						// Force PdfLoader remount to clear its internal error state
						setPdfLoaderKey(prev => prev + 1);
					}
				} catch (e) {
					console.error("Failed to refresh PDF URL:", e);
				} finally {
					setIsRefreshingUrl(false);
				}
			}
		},
		[onRefreshUrl, isRefreshingUrl]
	);

	// Refs
	const highlighterUtilsRef = useRef<PdfHighlighterUtils | null>(null);
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	const pdfDocumentRef = useRef<any>(null);
	const containerRef = useRef<HTMLDivElement>(null);
	// When true, skip scrolling on the next activeHighlight change (e.g., when clicking directly on a highlight)
	const blockScrollOnNextHighlight = useRef(false);
	// Track previous scale to detect scale changes (for overlay recreation timing)
	const prevScaleRef = useRef<number | null>(null);

	// State
	const [currentSelection, setCurrentSelection] = useState<PdfSelection | null>(null);
	const [, setCurrentGhostHighlight] = useState<GhostHighlight | null>(null);
	const [scale, setScale] = useState(1.0);
	// Ref so ResizeObserver callbacks (which close over a stale scale) can re-apply the current scale
	const scaleRef = useRef(1.0);
	const [currentPage, setCurrentPage] = useState(1);
	const [numPages, setNumPages] = useState<number | null>(null);
	const [showScrollToTop] = useState(false);
	const [pdfReady, setPdfReady] = useState(false);
	/** Bumped on PDF.js `pagerendered` so annotation-card restore can retry when page views exist */
	// Jump to page when citation (P.X) is clicked
	useEffect(() => {
		if (jumpToPage == null || !pdfReady) return;
		const viewer = highlighterUtilsRef.current?.getViewer();
		if (viewer) {
			viewer.currentPageNumber = jumpToPage;
		}
	}, [jumpToPage, pdfReady]);
	const [pdfLayoutTick, setPdfLayoutTick] = useState(0);
	/**
	 * Bumped once the PDF.js PDFViewer instance is actually ready.
	 * The library initialises the viewer with a 100ms debounce inside a useLayoutEffect,
	 * so getViewer() returns null for a short window after pdfReady becomes true.
	 * Polling after pdfReady ensures both the pagerendered subscriber and the restore
	 * effect re-run once the viewer is genuinely available.
	 */
	const [viewerReadyTick, setViewerReadyTick] = useState(0);
	const [highlightColor, setHighlightColor] = useState<HighlightColor>("blue");

	// Search hook
	const search = usePdfSearch({
		highlighterUtilsRef,
		pdfDocumentRef,
		setCurrentPage,
		explicitSearchTerm,
		pdfReady,
		activeHighlightId: activeHighlight?.id,
	});

	// Convert PaperHighlights to ExtendedHighlights
	// Memoize to prevent the scroll-to-highlight effect from re-running on every render
	const extendedHighlights: ExtendedHighlight[] = useMemo(
		() => highlights
			.map(h => {
				const ext = paperHighlightToExtended(h);
				if (ext) {
					ext.hasAnnotation = annotations.some(a => a.highlight_id === h.id);
				}
				return ext;
			})
			.filter((h): h is ExtendedHighlight => h !== null),
		[highlights, annotations]
	);

	/**
	 * Highlight rectangles (react-pdf-highlighter-extended) are re-laid out from scaled positions on
	 * every scroll/textlayerrender. During zoom, PDF.js fires many pagerendereds and ResizeObserver
	 * updates — rects jump frame-to-frame (flashy). We hide the highlight layer until layout quiets.
	 */
	const [pdfHighlightsSuppressedForZoom, setPdfHighlightsSuppressedForZoom] = useState(false);
	const pendingZoomHighlightRef = useRef(false);
	const zoomHighlightDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
	/** Bumped on each zoom press / safety timeout so in-flight rAF scroll checks don't unsuppress for a stale zoom. */
	const zoomHighlightSessionRef = useRef(0);
	const ZOOM_HIGHLIGHT_DEBOUNCE_MS = 300;
	const ZOOM_SCROLL_STABLE_MAX_FRAMES = 45;
	/** Consecutive rAF frames with matching scrollTop before we trust scroll has settled. */
	const ZOOM_SCROLL_STABLE_MATCHES_NEEDED = 2;

	/** Wait until scrollTop matches across several rAF samples (PDF.js can nudge scroll for multiple frames). */
	const finishZoomWhenScrollStable = useCallback((session: number) => {
		let prevScroll: number | undefined;
		let stableMatches = 0;
		let framesLeft = ZOOM_SCROLL_STABLE_MAX_FRAMES;
		const unsuppressAfterPaint = () => {
			requestAnimationFrame(() => {
				requestAnimationFrame(() => {
					requestAnimationFrame(() => {
						if (session !== zoomHighlightSessionRef.current || !pendingZoomHighlightRef.current) return;
						pendingZoomHighlightRef.current = false;
						setPdfHighlightsSuppressedForZoom(false);
					});
				});
			});
		};
		const tick = () => {
			requestAnimationFrame(() => {
				if (session !== zoomHighlightSessionRef.current || !pendingZoomHighlightRef.current) return;
				const el = highlighterUtilsRef.current?.getViewer()?.container as HTMLElement | undefined;
				const cur = el?.scrollTop ?? 0;
				if (prevScroll !== undefined && Math.abs(cur - prevScroll) < 0.5) {
					stableMatches += 1;
					if (stableMatches >= ZOOM_SCROLL_STABLE_MATCHES_NEEDED) {
						unsuppressAfterPaint();
						return;
					}
				} else {
					stableMatches = 0;
				}
				prevScroll = cur;
				if (--framesLeft <= 0) {
					unsuppressAfterPaint();
					return;
				}
				tick();
			});
		};
		tick();
	}, []);

	// Zoom controls
	const zoomIn = useCallback(() => {
		if (zoomHighlightDebounceRef.current) {
			clearTimeout(zoomHighlightDebounceRef.current);
			zoomHighlightDebounceRef.current = null;
		}
		zoomHighlightSessionRef.current += 1;
		setScale((prev) => Math.min(prev + 0.25, 3));
		pendingZoomHighlightRef.current = true;
		setPdfHighlightsSuppressedForZoom(true);
	}, []);

	const zoomOut = useCallback(() => {
		if (zoomHighlightDebounceRef.current) {
			clearTimeout(zoomHighlightDebounceRef.current);
			zoomHighlightDebounceRef.current = null;
		}
		zoomHighlightSessionRef.current += 1;
		setScale((prev) => Math.max(prev - 0.25, 0.5));
		pendingZoomHighlightRef.current = true;
		setPdfHighlightsSuppressedForZoom(true);
	}, []);

	// Apply scale changes directly to the viewer
	// (workaround for react-pdf-highlighter-extended not responding to pdfScaleValue prop changes)
	useEffect(() => {
		scaleRef.current = scale;
		const viewer = highlighterUtilsRef.current?.getViewer();
		if (!viewer) return;
		viewer.currentScaleValue = String(scale);

		// Guard the currentScaleValue setter against the library's stale ResizeObserver.
		// The library's useLayoutEffect captures pdfScaleValue at the time [highlights, selectionTip,
		// onSelectionFinished] last changed — NOT when pdfScaleValue changes — so its ResizeObserver
		// calls handleScaleValue() with an old scale value on every container resize (e.g., when a
		// horizontal scrollbar appears at 1.25× that wasn't present at 1.0×). This triggers a
		// 1.25→1→1.25 scale sequence in PDF.js, causing 3+ extra page canvas redraws that visually
		// flash the PDF content. Block any scale reversion while zoom animation is in progress.
		let proto: object | null = Object.getPrototypeOf(viewer);
		let originalDescriptor: PropertyDescriptor | undefined;
		while (proto) {
			originalDescriptor = Object.getOwnPropertyDescriptor(proto, 'currentScaleValue');
			if (originalDescriptor?.set) break;
			proto = Object.getPrototypeOf(proto);
		}
		const originalSet = originalDescriptor?.set;
		if (!originalSet) return;

		Object.defineProperty(viewer as object, 'currentScaleValue', {
			get: originalDescriptor!.get,
			set(value: string) {
				// During zoom animation, block any setter call that would revert to an old scale
				if (pendingZoomHighlightRef.current) {
					const num = parseFloat(value);
					if (!isNaN(num) && Math.abs(num - scaleRef.current) > 0.001) {
						return;
					}
				}
				originalSet.call(this, value);
			},
			configurable: true,
		});

		return () => {
			// Remove the instance-level override so the prototype setter is used again.
			// The new effect run will re-install it with the updated scale.
			try {
				// eslint-disable-next-line @typescript-eslint/no-explicit-any
				delete (viewer as any).currentScaleValue;
			} catch {
				// ignore
			}
		};
	}, [scale]);

	// Safety: never leave highlight overlays suppressed if pagerendered never settles.
	useEffect(() => {
		if (!pdfHighlightsSuppressedForZoom) return;
		const id = setTimeout(() => {
			if (zoomHighlightDebounceRef.current) {
				clearTimeout(zoomHighlightDebounceRef.current);
				zoomHighlightDebounceRef.current = null;
			}
			zoomHighlightSessionRef.current += 1;
			pendingZoomHighlightRef.current = false;
			setPdfHighlightsSuppressedForZoom(false);
		}, 3000);
		return () => clearTimeout(id);
	}, [pdfHighlightsSuppressedForZoom]);

	// Re-apply scale after container resizes to override the library's stale ResizeObserver
	// (the library's ResizeObserver captures a stale pdfScaleValue due to missing dependency)
	useEffect(() => {
		const container = containerRef.current;
		if (!container) return;

		const resizeObserver = new ResizeObserver(() => {
			// Use setTimeout to ensure our scale setting comes after the library's
			setTimeout(() => {
				const viewer = highlighterUtilsRef.current?.getViewer();
				if (viewer && viewer.currentScaleValue !== String(scale)) {
					viewer.currentScaleValue = String(scale);
				}
			}, 0);
		});

		resizeObserver.observe(container);
		return () => resizeObserver.disconnect();
	}, [scale]);

	// Page navigation
	const goToPreviousPage = useCallback(() => {
		if (currentPage > 1) {
			const viewer = highlighterUtilsRef.current?.getViewer();
			if (viewer) {
				viewer.currentPageNumber = currentPage - 1;
				setCurrentPage(currentPage - 1);
			}
		}
	}, [currentPage]);

	const goToNextPage = useCallback(() => {
		if (numPages && currentPage < numPages) {
			const viewer = highlighterUtilsRef.current?.getViewer();
			if (viewer) {
				viewer.currentPageNumber = currentPage + 1;
				setCurrentPage(currentPage + 1);
			}
		}
	}, [currentPage, numPages]);

	const scrollToTop = useCallback(() => {
		const viewer = highlighterUtilsRef.current?.getViewer();
		if (viewer) {
			viewer.currentPageNumber = 1;
			setCurrentPage(1);
		}
	}, []);

	// Handle selection
	const handleSelection = useCallback(
		(selection: PdfSelection) => {
			setCurrentSelection(selection);
			setSelectedText(selection.content.text || "");
			setIsHighlightInteraction(false);

			const domSelection = window.getSelection();
			if (domSelection && domSelection.rangeCount > 0) {
				const range = domSelection.getRangeAt(0);
				const rect = range.getBoundingClientRect();
				const clientRects = range.getClientRects();
				// #region agent log
				fetch("http://127.0.0.1:7848/ingest/1ffc24a3-d0c6-4802-9576-899d9a9fb32b", {
					method: "POST",
					headers: {
						"Content-Type": "application/json",
						"X-Debug-Session-Id": "434c20",
					},
					body: JSON.stringify({
						sessionId: "434c20",
						hypothesisId: "H1-H4",
						location: "PdfHighlighterViewer.tsx:handleSelection",
						message: "selection range rects",
						data: {
							union: {
								top: rect.top,
								bottom: rect.bottom,
								left: rect.left,
								height: rect.height,
							},
							clientRectCount: clientRects.length,
							innerHeight: typeof window !== "undefined" ? window.innerHeight : null,
						},
						timestamp: Date.now(),
						runId: "pre-fix",
					}),
				}).catch(() => {});
				// #endregion
				setTooltipPosition({
					x: rect.left,
					y: rect.bottom,
				});
			}
		},
		[setSelectedText, setTooltipPosition, setIsHighlightInteraction]
	);

	// Handle ghost highlight creation
	const handleCreateGhostHighlight = useCallback(
		(ghostHighlight: GhostHighlight) => {
			setCurrentGhostHighlight(ghostHighlight);
		},
		[]
	);

	// Handle ghost highlight removal
	const handleRemoveGhostHighlight = useCallback(() => {
		setCurrentGhostHighlight(null);
	}, []);

	// Handle adding a highlight from the menu
	const pendingAnnotateRef = useRef(false);
	const prevHighlightsLenRef = useRef(highlights.length);
	useEffect(() => {
		if (pendingAnnotateRef.current && highlights.length > prevHighlightsLenRef.current) {
			pendingAnnotateRef.current = false;
			const newest = highlights[highlights.length - 1];
			if (newest?.id) onAnnotateRequest?.(newest.id);
		}
		prevHighlightsLenRef.current = highlights.length;
	}, [highlights, onAnnotateRequest]);

	const handleAddHighlightFromMenu = useCallback(
		(text: string, doAnnotate?: boolean) => {
			if (currentSelection) {
				// Block scroll-to-highlight since we're creating a new one at the current location
				blockScrollOnNextHighlight.current = true;
				// Clear active highlight to prevent scroll back when highlights array updates
				setActiveHighlight(null);

				const ghostHighlight = currentSelection.makeGhostHighlight();
				addHighlight(
					text,
					ghostHighlight.position as ScaledPosition,
					ghostHighlight.position.boundingRect.pageNumber,
					doAnnotate,
					highlightColor
				);
				if (doAnnotate) pendingAnnotateRef.current = true;
				setCurrentSelection(null);
				setSelectedText("");
				setTooltipPosition(null);
			}
		},
		[currentSelection, addHighlight, setSelectedText, setTooltipPosition, highlightColor, setActiveHighlight]
	);

	const highlightHasPersistedAnnotations = useCallback(
		(hid: string) => annotations.some(a => a.highlight_id === hid),
		[annotations]
	);

	// Handle translate request from the selection menu
	const handleTranslate = useCallback(async () => {
		if (!selectedText) return;
		setIsTranslating(true);
		setTranslationText(null);
		setTranslationPos(tooltipPosition);
		try {
			const data = await fetchFromApi("/api/translate", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ text: selectedText }),
			});
			if (data.translation) {
				setTranslationText(data.translation);
			} else {
				// No result — hide popover
				setTranslationPos(null);
			}
		} catch {
			setTranslationPos(null);
		} finally {
			setIsTranslating(false);
		}
	}, [selectedText, tooltipPosition]);

	// Handle highlight click
	const handleHighlightClick = useCallback(
		(viewportHighlight: ViewportHighlight<ExtendedHighlight>, event: MouseEvent) => {
			setIsHighlightInteraction(true);
			setSelectedText(viewportHighlight.content?.text || viewportHighlight.raw_text || "");

			const hid = viewportHighlight.id;
			const originalHighlight = hid ? extendedHighlights.find((h) => h.id === hid) : undefined;
			if (originalHighlight) {
				const paperHighlight = extendedToPaperHighlight(originalHighlight);
				// Don't scroll - the highlight is already in view since user just clicked it
				blockScrollOnNextHighlight.current = true;
				setActiveHighlight(paperHighlight);
			}

			const openMenuAtHighlight = () => {
				const target = event.target as HTMLElement;
				const partsContainer = target.classList.contains("TextHighlight__parts")
					? target
					: (target.closest(".TextHighlight__parts") as HTMLElement | null);
				let anchorX = event.clientX;
				let anchorY = event.clientY + 20;
				if (partsContainer) {
					const parts = Array.from(partsContainer.querySelectorAll(".TextHighlight__part"));
					if (parts.length > 0) {
						const rects = parts.map((p) => p.getBoundingClientRect());
						const bottomRect = rects.reduce((prev, curr) =>
							curr.top > prev.top ? curr : prev
						);
						anchorX = bottomRect.left;
						anchorY = bottomRect.bottom;
					}
				}
				setTooltipPosition({ x: anchorX, y: anchorY });
			};

			if (!hid) return;

			openMenuAtHighlight();
		},
		[
			setIsHighlightInteraction,
			setSelectedText,
			setTooltipPosition,
			setActiveHighlight,
			extendedHighlights,

			highlightHasPersistedAnnotations,
			highlights,
		]
	);

	// Handle outside click to dismiss tooltip
	useEffect(() => {
		if (!tooltipPosition) return;

		const handleOutsideClick = (e: MouseEvent) => {
			const target = e.target as HTMLElement;
			// Let handleHighlightClick handle highlight clicks — don't close here
			if (target.closest?.('.TextHighlight__parts, .TextHighlight__part')) return;
			const tooltipElement = document.querySelector(".fixed.z-30");
			if (!tooltipElement) return;

			if (!tooltipElement.contains(target)) {
				setTimeout(() => {
					setIsHighlightInteraction(false);
					setSelectedText("");
					setTooltipPosition(null);
					setIsAnnotating(false);
					setCurrentSelection(null);
				}, 10);
			}
		};

		const timerId = setTimeout(() => {
			document.addEventListener("mousedown", handleOutsideClick);
		}, 100);

		return () => {
			clearTimeout(timerId);
			document.removeEventListener("mousedown", handleOutsideClick);
		};
	}, [
		tooltipPosition,
		setIsHighlightInteraction,
		setSelectedText,
		setTooltipPosition,
		setIsAnnotating,
	]);

	// Click outside the inline annotation card (and outside highlight / sidebar rows) clears active highlight
	useEffect(() => {
		if (!activeHighlight) return;

		const handleDocumentMouseDown = (e: MouseEvent) => {
			const target = e.target as HTMLElement | null;
			if (!target) return;

			if (target.closest("[data-inline-annotation-card]")) return;
			// Entire highlight layer + our wrapper: mousedown target is not always a .TextHighlight__part
			// (gaps, wrapper, or stacking) but the user is still interacting with a highlight.
			if (target.closest(".PdfHighlighter__highlight-layer")) return;
			if (target.closest("[data-pdf-text-highlight]")) return;
			if (target.closest(".TextHighlight__parts, .TextHighlight__part")) return;
			if (target.closest("[data-annotation-sidebar-row]")) return;
			if (target.closest("[data-inline-annotation-menu]")) return;

			setActiveHighlight(null);
		};

		document.addEventListener("mousedown", handleDocumentMouseDown);
		return () => document.removeEventListener("mousedown", handleDocumentMouseDown);
	}, [activeHighlight, setActiveHighlight]);

	// Poll for the PDF.js viewer instance becoming available.
	// The library initialises it with a 100ms debounce, so getViewer() returns null
	// immediately after pdfReady. We bump viewerReadyTick when it's actually set,
	// which re-triggers the pagerendered subscriber and the restore effect below.
	useEffect(() => {
		if (!pdfReady) return;
		let timerId: ReturnType<typeof setTimeout>;
		const check = () => {
			const viewer = highlighterUtilsRef.current?.getViewer();
			if (viewer) {
				setViewerReadyTick(t => t + 1);
			} else {
				timerId = setTimeout(check, 50);
			}
		};
		// Start polling slightly after the library's 100ms debounce
		timerId = setTimeout(check, 120);
		return () => clearTimeout(timerId);
	}, [pdfReady]);

	// Re-run restore attempts as each PDF page finishes rendering (page views may be missing before then)
	useEffect(() => {
		if (!pdfReady || numPages == null) return;
		const viewer = highlighterUtilsRef.current?.getViewer();
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		const bus = (viewer as any)?.eventBus;
		if (!bus?.on) return;
		const onPageRendered = () => {
			setPdfLayoutTick((t) => t + 1);
			if (!pendingZoomHighlightRef.current) return;
			if (zoomHighlightDebounceRef.current) {
				clearTimeout(zoomHighlightDebounceRef.current);
			}
			zoomHighlightDebounceRef.current = setTimeout(() => {
				zoomHighlightDebounceRef.current = null;
				if (!pendingZoomHighlightRef.current) return;
				const session = zoomHighlightSessionRef.current;
				finishZoomWhenScrollStable(session);
			}, ZOOM_HIGHLIGHT_DEBOUNCE_MS);
		};
		bus.on("pagerendered", onPageRendered);
		return () => {
			bus.off("pagerendered", onPageRendered);
			if (zoomHighlightDebounceRef.current) {
				clearTimeout(zoomHighlightDebounceRef.current);
				zoomHighlightDebounceRef.current = null;
			}
		};
	}, [pdfReady, numPages, viewerReadyTick, finishZoomWhenScrollStable]);


	// Keep the module-level store in sync so HighlightContainer (in a separate React root) can react
	useEffect(() => {
		activeHighlightStore.set(activeHighlight?.id);
	}, [activeHighlight]);

	// Scroll to active highlight when it changes (unless blocked, e.g., when clicking directly on a highlight)
	useEffect(() => {
		if (activeHighlight?.id && highlighterUtilsRef.current) {
			if (blockScrollOnNextHighlight.current) {
				blockScrollOnNextHighlight.current = false;
				return;
			}
			const extendedHighlight = extendedHighlights.find(
				(h) => h.id === activeHighlight.id
			);
			if (extendedHighlight) {
				highlighterUtilsRef.current.scrollToHighlight(extendedHighlight);
			}
		}
	}, [activeHighlight, extendedHighlights]);

	// Hover card: show annotations on highlight hover when margin cards are hidden
	useEffect(() => {
		const container = containerRef.current;
		if (!container) return;

		const getHighlightId = (target: EventTarget | null): string | null => {
			const el = target as HTMLElement | null;
			if (!el?.closest) return null;
			// DOM overlay highlights
			const overlay = el.closest<HTMLElement>(".text-match-highlight-overlay[data-highlight-id]");
			if (overlay) return overlay.getAttribute("data-highlight-id");
			// Positioned highlights from HighlightContainer
			const positioned = el.closest<HTMLElement>("[data-pdf-text-highlight][data-highlight-id]");
			if (positioned) return positioned.getAttribute("data-highlight-id");
			return null;
		};

		const onMouseOver = (e: MouseEvent) => {
			const hid = getHighlightId(e.target);
			if (!hid) return;
			// Only show if this highlight has persisted annotations
			if (!annotations.some((a) => a.highlight_id === hid)) return;
			setHoverHighlightId(hid);
			setHoverPosition({ x: e.clientX + 12, y: e.clientY + 12 });
		};

		const onMouseOut = (e: MouseEvent) => {
			const fromHid = getHighlightId(e.target);
			const toHid = getHighlightId(e.relatedTarget);
			// Only hide if we actually left the highlight (not moving between parts of the same highlight)
			if (fromHid && fromHid === toHid) return;
			if (fromHid) {
				setHoverHighlightId(null);
				setHoverPosition(null);
			}
		};

		// Dismiss on click (highlight becomes active / tooltip opens)
		const onMouseDown = () => {
			setHoverHighlightId(null);
			setHoverPosition(null);
		};

		container.addEventListener("mouseover", onMouseOver);
		container.addEventListener("mouseout", onMouseOut);
		container.addEventListener("mousedown", onMouseDown);
		return () => {
			container.removeEventListener("mouseover", onMouseOver);
			container.removeEventListener("mouseout", onMouseOut);
			container.removeEventListener("mousedown", onMouseDown);
		};
	}, [annotations]);

	// Update current page when user scrolls through the PDF
	useEffect(() => {
		if (!pdfReady) return;

		const pdfViewer = document.querySelector(".pdfViewer");
		if (!pdfViewer) return;

		// Track visibility ratio for each page
		const pageVisibility = new Map<number, number>();
		let lastReportedPage = 1;

		const observer = new IntersectionObserver(
			(entries) => {
				entries.forEach((entry) => {
					const pageNum = parseInt(
						entry.target.getAttribute("data-page-number") || "0",
						10
					);
					if (pageNum > 0) {
						if (entry.isIntersecting) {
							pageVisibility.set(pageNum, entry.intersectionRatio);
						} else {
							pageVisibility.delete(pageNum);
						}
					}
				});

				// Find the page with the highest visibility
				let maxVisibility = 0;
				let mostVisiblePage = lastReportedPage;
				pageVisibility.forEach((ratio, pageNum) => {
					if (ratio > maxVisibility) {
						maxVisibility = ratio;
						mostVisiblePage = pageNum;
					}
				});

				if (mostVisiblePage !== lastReportedPage && maxVisibility > 0) {
					lastReportedPage = mostVisiblePage;
					setCurrentPage(mostVisiblePage);
				}
			},
			{
				root: pdfViewer.closest(".pdfViewerContainer") || pdfViewer.parentElement,
				threshold: [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1],
			}
		);

		// Observe all page elements
		const pages = pdfViewer.querySelectorAll(".page[data-page-number]");
		pages.forEach((page) => observer.observe(page));

		// Also observe new pages as they're added (for lazy loading)
		const mutationObserver = new MutationObserver((mutations) => {
			mutations.forEach((mutation) => {
				mutation.addedNodes.forEach((node) => {
					if (node instanceof Element) {
						const newPages = node.matches(".page[data-page-number]")
							? [node]
							: node.querySelectorAll(".page[data-page-number]");
						newPages.forEach((page) => observer.observe(page));
					}
				});
			});
		});

		mutationObserver.observe(pdfViewer, { childList: true, subtree: true });

		return () => {
			observer.disconnect();
			mutationObserver.disconnect();
		};
	}, [pdfReady]);

	// Intercept external links in PDF annotations for security
	useEffect(() => {
		const container = containerRef.current;
		if (!container) return;

		const handleLinkClick = (event: MouseEvent) => {
			const target = event.target as HTMLElement;
			const link = target.closest("a");

			if (!link) return;

			// Check if this is inside the annotation layer
			const annotationLayer = link.closest(".annotationLayer");
			if (!annotationLayer) return;

			const href = link.getAttribute("href");
			if (!href) return;

			// Internal document links start with # (page anchors, named destinations)
			if (href.startsWith("#")) {
				// Allow internal links to work normally
				return;
			}

			// External link detected - intercept and warn
			event.preventDefault();
			event.stopPropagation();

			// Mark it visually as external
			const linkSection = link.closest("section");
			if (linkSection) {
				linkSection.setAttribute("data-external-link", "true");
			}

			const proceed = window.confirm(
				`This PDF contains a link to an external website:\n\n${href}\n\nDo you want to open it in a new tab?`
			);

			if (proceed) {
				window.open(href, "_blank", "noopener,noreferrer");
			}
		};

		// Mark external links on render for visual styling
		const markExternalLinks = () => {
			const links = container.querySelectorAll(".annotationLayer a[href]");
			links.forEach((link) => {
				const href = link.getAttribute("href");
				if (href && !href.startsWith("#")) {
					const section = link.closest("section");
					if (section) {
						section.setAttribute("data-external-link", "true");
					}
				}
			});
		};

		// Use capture phase to intercept before PDF.js handles the click
		container.addEventListener("click", handleLinkClick, true);

		// Mark existing external links and watch for new ones
		markExternalLinks();
		const observer = new MutationObserver(markExternalLinks);
		observer.observe(container, { childList: true, subtree: true });

		return () => {
			container.removeEventListener("click", handleLinkClick, true);
			observer.disconnect();
		};
	}, [pdfReady]);

	// Cache for highlight page mappings
	const highlightPageMapRef = useRef<Map<string, number[]>>(new Map());

	// Create DOM-based overlays for highlights without position data
	// This handles both assistant highlights and legacy user highlights (backwards compatibility)
	// Uses MutationObserver to detect when text layers are added/recreated
	useEffect(() => {
		if (!pdfReady || !pdfDocumentRef.current) return;

		// Clear existing overlays (needed when scale changes so they can be recreated at new positions)
		document.querySelectorAll(".text-match-highlight-overlay").forEach((el) => el.remove());

		// Get all highlights without positions (assistant or legacy user highlights)
		const highlightsWithoutPosition = highlights.filter(
			(h) => !h.position && h.raw_text
		);

		if (highlightsWithoutPosition.length === 0) {
			highlightPageMapRef.current.clear();
			return;
		}

		// Function to create overlays for a specific text layer
		const createOverlaysForTextLayer = (textLayer: Element, pageNumber: number) => {
			for (const highlight of highlightsWithoutPosition) {
				const key = highlight.id || highlight.raw_text;
				const pages = highlightPageMapRef.current.get(key);

				// Check if this highlight belongs on this page
				if (!pages || !pages.includes(pageNumber)) continue;

				// Check if overlay already exists
				const existingOverlay = textLayer.querySelector(
					`.text-match-highlight-overlay[data-highlight-key="${CSS.escape(key)}"]`
				);
				if (existingOverlay) continue;

				const overlayIsActive =
					Boolean(highlight.id) && highlight.id === activeHighlight?.id;
				const backgroundColor =
					highlight.role === "assistant"
						? getAssistantHighlightBackgroundRgba(overlayIsActive)
						: getUserHighlightBackgroundRgba(highlight.color, overlayIsActive);

				const overlays = createTextHighlightOverlays(
					textLayer,
					highlight.raw_text,
					"text-match-highlight-overlay",
					backgroundColor
				);

				// Make overlays clickable and navigate to annotation panel
				overlays.forEach((el) => {
					el.setAttribute("data-highlight-key", key);
					el.setAttribute("data-highlight-id", highlight.id || "");
					el.setAttribute("data-page-number", String(pageNumber));
					// Encode position from the overlay's computed style
					const left = el.style.left;
					const top = el.style.top;
					const width = el.style.width;
					const height = el.style.height;
					el.setAttribute("data-position", JSON.stringify({
						left: parseFloat(left),
						top: parseFloat(top),
						width: parseFloat(width),
						height: parseFloat(height),
						page: pageNumber,
					}));
					el.style.pointerEvents = "auto";
					el.style.cursor = "pointer";
					el.addEventListener("click", (e) => {
						e.stopPropagation();
						// Don't scroll - the highlight is already in view since user just clicked it
						blockScrollOnNextHighlight.current = true;
						setActiveHighlight(highlight);
						setIsHighlightInteraction(true);
						setSelectedText(highlight.raw_text);
						const hid = highlight.id;
						if (
							hid &&
		
							highlightHasPersistedAnnotations(hid)
						) {
							return;
						}
						if (
							hid &&
		
							highlightHasPersistedAnnotations(hid) &&
							highlight.position &&
							highlight.page_number
						) {
							const viewer = highlighterUtilsRef.current?.getViewer();
							const scrollContainer = viewer?.container as HTMLElement | undefined;
							if (viewer && scrollContainer) {
								const anchor = getAnnotationCardAnchorForHighlight(
									highlight,
									viewer,
									scrollContainer
								);
								if (anchor) {
									const targetScrollTop = anchor.top - scrollContainer.clientHeight / 2;
									scrollContainer.scrollTo({
										top: Math.max(0, targetScrollTop),
										behavior: "smooth",
									});
									return;
								}
							}
						}
						const rect = (e.target as HTMLElement).getBoundingClientRect();
						setTooltipPosition({
							x: rect.left,
							y: (e as MouseEvent).clientY + 20,
						});
					});
				});
			}
		};

		// Create overlays for all currently rendered text layers
		const createOverlaysForAllRenderedPages = () => {
			const textLayers = document.querySelectorAll(".page .textLayer");
			textLayers.forEach((textLayer) => {
				const pageEl = textLayer.closest(".page");
				const pageNum = pageEl?.getAttribute("data-page-number");
				if (pageNum) {
					createOverlaysForTextLayer(textLayer, parseInt(pageNum, 10));
				}
			});
		};

		// Collect all rendered highlight positions from the DOM and notify via callback
		const notifyOverlaysCreated = () => {
			if (!onOverlaysCreated) return;

			const positions = new Map<string, RenderedHighlightPosition>();
			const overlays = document.querySelectorAll(".text-match-highlight-overlay[data-highlight-id]");

			overlays.forEach((el) => {
				const highlightId = el.getAttribute("data-highlight-id");
				const positionData = el.getAttribute("data-position");

				if (highlightId && positionData && !positions.has(highlightId)) {
					try {
						const parsed = JSON.parse(positionData) as RenderedHighlightPosition;
						positions.set(highlightId, parsed);
					} catch (e) {
						console.warn("Failed to parse position data for highlight", highlightId, e);
					}
				}
			});

			onOverlaysCreated(positions);
		};

		// Populate page cache for highlights (needed for both immediate creation and MutationObserver)
		const ensurePageMappings = async () => {
			for (const highlight of highlightsWithoutPosition) {
				const key = highlight.id || highlight.raw_text;
				if (!highlightPageMapRef.current.has(key)) {
					const pages = await findTextPages(
						highlight.raw_text,
						pdfDocumentRef.current,
						highlight.page_number
					);
					highlightPageMapRef.current.set(key, pages);
				}
			}
		};

		// Track if this is a scale change for delayed overlay creation
		const isScaleChange = prevScaleRef.current !== null && prevScaleRef.current !== scale;
		prevScaleRef.current = scale;

		// On scale change, delay overlay creation to let pdf.js apply CSS transforms
		// On initial load or highlight changes, create immediately
		const creationDelay = isScaleChange ? 50 : 0;

		const timeoutId = setTimeout(() => {
			ensurePageMappings().then(() => {
				createOverlaysForAllRenderedPages();
				notifyOverlaysCreated();
			});
		}, creationDelay);

		// Track pending timeouts per page to debounce rapid mutations
		const pendingTimeouts = new Map<number, ReturnType<typeof setTimeout>>();

		// Use MutationObserver to detect when text layers are added/modified
		const observer = new MutationObserver((mutations) => {
			const textLayersToProcess = new Set<Element>();

			for (const mutation of mutations) {
				// Check added nodes for text layers
				mutation.addedNodes.forEach((node) => {
					if (node instanceof Element) {
						// Check if the node itself is a textLayer
						if (node.classList?.contains("textLayer")) {
							textLayersToProcess.add(node);
						}
						// Check if any descendants are textLayers
						const textLayers = node.querySelectorAll?.(".textLayer");
						textLayers?.forEach((textLayer) => {
							textLayersToProcess.add(textLayer);
						});
						// Check if the node was added to an existing textLayer (spans being repopulated)
						const parentTextLayer = node.closest?.(".textLayer");
						if (parentTextLayer) {
							textLayersToProcess.add(parentTextLayer);
						}
					}
				});
			}

			// Process each unique textLayer once with debounced delay
			textLayersToProcess.forEach((textLayer) => {
				const pageEl = textLayer.closest(".page");
				const pageNum = pageEl?.getAttribute("data-page-number");
				if (pageNum) {
					const pageNumber = parseInt(pageNum, 10);
					// Clear any pending timeout for this page to debounce
					const existingTimeout = pendingTimeouts.get(pageNumber);
					if (existingTimeout) {
						clearTimeout(existingTimeout);
					}
					// Schedule overlay creation with delay to ensure spans are populated
					const timeout = setTimeout(() => {
						pendingTimeouts.delete(pageNumber);
						createOverlaysForTextLayer(textLayer, pageNumber);
						notifyOverlaysCreated();
					}, 100);
					pendingTimeouts.set(pageNumber, timeout);
				}
			});
		});

		// Observe the PDF viewer container for changes
		const pdfViewer = document.querySelector(".pdfViewer");
		if (pdfViewer) {
			observer.observe(pdfViewer, {
				childList: true,
				subtree: true,
			});
		}

		return () => {
			observer.disconnect();
			clearTimeout(timeoutId);
			// Clear any pending timeouts
			pendingTimeouts.forEach((timeout) => clearTimeout(timeout));
			pendingTimeouts.clear();
		};
	}, [
		pdfReady,
		highlights,
		scale,
		onOverlaysCreated,
		activeHighlight,

		highlightHasPersistedAnnotations,
	]);

	return (
		<div
			ref={containerRef}
			className="flex flex-col w-full h-full min-h-0 overflow-x-visible overflow-y-hidden"
			id="pdf-container"
		>
			{/* Toolbar */}
			<PdfToolbar
				currentPage={currentPage}
				numPages={numPages}
				goToPreviousPage={goToPreviousPage}
				goToNextPage={goToNextPage}
				searchText={search.searchText}
				showSearchInput={search.showSearchInput}
				setShowSearchInput={search.setShowSearchInput}
				searchInputRef={search.searchInputRef}
				handleSearchChange={search.handleSearchChange}
				handleSearchSubmit={search.handleSearchSubmit}
				handleClearSearch={search.handleClearSearch}
				isSearching={search.isSearching}
				matchPages={search.matchPages}
				currentMatchIndex={search.currentMatchIndex}
				goToPreviousMatch={search.goToPreviousMatch}
				goToNextMatch={search.goToNextMatch}
				lastSearchTermRef={search.lastSearchTermRef}
				scale={scale}
				zoomIn={zoomIn}
				zoomOut={zoomOut}
				paperStatus={paperStatus}
				handleStatusChange={handleStatusChange}
				highlightColor={highlightColor}
				setHighlightColor={setHighlightColor}

				isReadMode={isReadMode}
				onToggleReadMode={onToggleReadMode}
			/>

			{/* PDF Viewer — overflow-x-visible so margin annotation cards beside the page are not clipped */}
			<div
				className={cn(
					"flex-1 min-h-0 overflow-x-visible overflow-y-hidden relative",
					pdfHighlightsSuppressedForZoom && "pdf-zoom-layout-pending",
					sidePanelOpen && "pdf-align-left"
				)}
			>
				<PdfLoader
					key={pdfLoaderKey}
					document={effectivePdfUrl}
					workerSrc="/pdf.worker.mjs"
					beforeLoad={() => <EnigmaticLoadingExperience />}
					onError={handlePdfError}
					errorMessage={(error) =>
						isRefreshingUrl ? (
							<EnigmaticLoadingExperience />
						) : (
							<div className="p-4 text-red-500">
								Error loading PDF: {error.message}
							</div>
						)
					}
				>
					{(pdfDocument) => {
						return (
							<>
								<PdfDocumentSync
									pdfDocument={pdfDocument}
									pdfDocumentRef={pdfDocumentRef}
									setPdfReady={setPdfReady}
									setNumPages={setNumPages}
								/>
								<PdfHighlighter
									pdfDocument={pdfDocument}
									pdfScaleValue={scale}
									highlights={extendedHighlights}
									onSelection={handleSelection}
									onCreateGhostHighlight={handleCreateGhostHighlight}
									onRemoveGhostHighlight={handleRemoveGhostHighlight}
									enableAreaSelection={(event) => event.altKey}
									utilsRef={(utils) => {
										highlighterUtilsRef.current = utils;
									}}
									style={{
										height: "100%",
									}}
									textSelectionColor={PDF_TEXT_SELECTION_FILL}
								>
									<HighlightContainer onHighlightClick={handleHighlightClick} />
								</PdfHighlighter>
							</>
						);
					}}
				</PdfLoader>
			</div>

			{/* Inline Annotation Menu */}
			{tooltipPosition && (
				<InlineAnnotationMenu
					selectedText={selectedText}
					tooltipPosition={tooltipPosition}
					setSelectedText={setSelectedText}
					setTooltipPosition={setTooltipPosition}
					setIsAnnotating={setIsAnnotating}
					highlights={highlights}
					setHighlights={setHighlights}
					isHighlightInteraction={isHighlightInteraction}
					activeHighlight={activeHighlight}
					addHighlight={handleAddHighlightFromMenu}
					removeHighlight={removeHighlight}
					setUserMessageReferences={setUserMessageReferences}
				onTranslate={handleTranslate}
			onAnnotateRequest={() => {
						/* handled by handleAddHighlightFromMenu + pendingAnnotateRef */
					}}
			/>
		)}


		{/* Translation popover */}
		<TranslationPopover
			text={translationText || ""}
			isLoading={isTranslating}
			position={translationPos}
			onClose={() => { setTranslationPos(null); setTranslationText(null); }}
		/>

			{/* Annotation hover card — shown on highlight hover when margin cards are hidden */}
			{hoverHighlightId && hoverPosition && (
				<AnnotationHoverCard
					annotations={annotations.filter((a) => a.highlight_id === hoverHighlightId)}
					position={hoverPosition}
					user={currentUser ?? null}
				/>
			)}

			{/* Scroll to top button */}
			{showScrollToTop && (
				<Button
					onClick={scrollToTop}
					size="sm"
					variant="secondary"
					className="fixed bottom-4 right-4 z-20 rounded-full w-10 h-10 p-0 shadow-lg"
				>
					<ChevronUp size={16} />
				</Button>
			)}
		</div>
	);
}
