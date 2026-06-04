import {
    ChatMessage,
    PaperData,
    PaperHighlight,
    PaperHighlightAnnotation,
    CreditUsage,
    Reference,
} from '@/lib/schema';
import { RenderedHighlightPosition } from './PdfHighlighterViewer';
import {
    X,
    Loader,
    ArrowUp,
    Share2Icon,
    LockIcon,
    Sparkle,
    Check,
    Route,
    Pencil,
    ChevronLeft,
    ChevronRight,
} from 'lucide-react';
import { Textarea } from '@/components/ui/textarea';
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    DropdownMenuSub,
    DropdownMenuSubTrigger,
    DropdownMenuSubContent,
} from "@/components/ui/dropdown-menu";
import { Input } from '@/components/ui/input';
import { ChatHistorySkeleton } from '@/components/ChatHistorySkeleton';
import { Button } from '@/components/ui/button';
import { AnnotationsView } from '@/components/AnnotationsView';
import PaperMetadata from '@/components/PaperMetadata';
import { ChatMessageActions } from '@/components/ChatMessageActions';
import { GuardSummaryBar, FeedbackButtons } from '@/components/GuardSummaryBar';
import { parseGuardResult } from '@/components/utils/parseGuardResult';
import { BranchDirectory } from '@/components/BranchDirectory';
import { AnimatedMarkdown, CopyableTable } from '@/components/AnimatedMarkdown';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeKatex from 'rehype-katex';
import remarkMath from 'remark-math';
import 'katex/dist/katex.min.css' // `rehype-katex` does not import the CSS for you
import CustomCitationLink from '@/components/utils/CustomCitationLink';
import { CitationWrapper } from '@/components/CitationContent';
import Link from 'next/link';
import { NotesPanel } from '@/components/NotesPanel';
import { ParsedPanel } from '@/components/ParsedPanel';
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card';
import React, { useState, useRef, useEffect, useMemo, useCallback, FormEvent } from 'react';
import { toast } from "sonner";
import { fetchFromApi, fetchStreamFromApi } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useSubscription, getChatCreditUsagePercentage, isChatCreditAtLimit, isChatCreditNearLimit } from '@/hooks/useSubscription';
import { Avatar, AvatarFallback, AvatarImage } from './ui/avatar';
import { getAlphaHashToBackgroundColor, getInitials } from '@/lib/utils';


interface SidePanelContentProps {
    rightSideFunction: string;
    paperData: PaperData;
    annotations: PaperHighlightAnnotation[];
    highlights: PaperHighlight[];
    handleHighlightClick: (highlight: PaperHighlight) => void;
    activeHighlight: PaperHighlight | null;
    isSharing: boolean;
    handleShare: () => void;
    handleUnshare: () => void;
    id: string;
    matchesCurrentCitation: (key: string, messageIndex: number) => boolean;
    handleCitationClickFromSummary: (citationKey: string, messageIndex: number) => void;
    setRightSideFunction: (value: string) => void;
    setExplicitSearchTerm: (value: string) => void;
    handleCitationClick: (key: string, messageIndex: number) => void;
    userMessageReferences: string[];
    setUserMessageReferences: React.Dispatch<React.SetStateAction<string[]>>;
    isMobile: boolean;
    renderedHighlightPositions?: Map<string, RenderedHighlightPosition>;
    composeHighlightId?: string | null;
    onComposeHighlightDismiss?: (cancelledHighlightId?: string | null) => void;
    addAnnotation?: (highlightId: string, content: string) => Promise<PaperHighlightAnnotation>;
	updateAnnotation?: (annotationId: string, content: string) => Promise<PaperHighlightAnnotation> | void;
}

interface ChatRequestBody {
    user_query: string;
    conversation_id: string | null;
    paper_id: string;
    user_references: string[];
    llm_provider?: string;
}

export function SidePanelContent({
    rightSideFunction,
    paperData,
    annotations,
    highlights,
    handleHighlightClick,
    activeHighlight,
    isSharing,
    handleShare,
    handleUnshare,
    id,
    matchesCurrentCitation,
    handleCitationClickFromSummary,
    setRightSideFunction,
    setExplicitSearchTerm,
    handleCitationClick,
    userMessageReferences,
    setUserMessageReferences,
    isMobile,
    renderedHighlightPositions,
    composeHighlightId,
    onComposeHighlightDismiss,
		updateAnnotation,
    addAnnotation,
}: SidePanelContentProps) {
    const { user } = useAuth();
    const [conversationId, setConversationId] = useState<string | null>(null);
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [currentMessage, setCurrentMessage] = useState('');
    const [hasMoreMessages, setHasMoreMessages] = useState(true);
    const [isLoadingMoreMessages, setIsLoadingMoreMessages] = useState(false);
    const [isStreaming, setIsStreaming] = useState(false);
    const [streamingChunks, setStreamingChunks] = useState<string[]>([]);
    const [streamingReferences, setStreamingReferences] = useState<Reference | undefined>(undefined);
    const [creditUsage, setCreditUsage] = useState<CreditUsage | null>(null);
    const { subscription, refetch: refetchSubscription } = useSubscription();
    const [selectedModel, setSelectedModel] = useState<string>('');
    const [availableModels, setAvailableModels] = useState<Record<string, string>>({});
    const [nextMonday, setNextMonday] = useState(new Date());
    const [pendingStarterQuestion, setPendingStarterQuestion] = useState<string | null>(null);
    const [pageNumberConversationHistory, setPageNumberConversationHistory] = useState(1);
    const [displayedText, setDisplayedText] = useState('');
    const [isTyping, setIsTyping] = useState(false);
    const [currentLoadingMessageIndex, setCurrentLoadingMessageIndex] = useState(0);
    const [errorState, setErrorState] = useState<{ failedUserMessage: string } | null>(null);
    const [isFetchingHistory, setIsFetchingHistory] = useState(true);
    // Tree conversation state
    const [editingMessageIndex, setEditingMessageIndex] = useState<number | null>(null);
    const [editContent, setEditContent] = useState('');
    const [conversationParentId, setConversationParentId] = useState<string | null>(null);
    const [conversationChildren, setConversationChildren] = useState<Array<{id: string; title: string; branchPointIndex: number}>>([]);
    const [branchPointIndex, setBranchPointIndex] = useState<number>(0);
    const [isBranching, setIsBranching] = useState(false);
    const fetchGenRef = useRef(0);  // generation counter: discard stale fetch results

    const messagesEndRef = useRef<HTMLDivElement | null>(null);
    const chatInputFormRef = useRef<HTMLFormElement | null>(null);
    const inputMessageRef = useRef<HTMLTextAreaElement | null>(null);
    const messagesContainerRef = useRef<HTMLDivElement | null>(null);

    const END_DELIMITER = "END_OF_STREAM";

    const COMPREHENSIVE_OVERVIEW_DISPLAY = "Create a comprehensive overview";
    const COMPREHENSIVE_OVERVIEW_PROMPT = "Create a comprehensive, thoughtful brief for this paper. Separate each section with clear headings covering: Key Takeaways (the main points in 2-3 bullets), Background (the problem and context), Key Contributions (what's novel about this work), Methods (the approach taken), Results (main findings), Limitations (weaknesses of the study), Open Questions (gaps for future research), and Important Figures/Tables (which visuals to pay attention to). This should serve as a helpful guided reading before I dive into the paper myself.";

    const defaultStarterQuestions = [
        COMPREHENSIVE_OVERVIEW_DISPLAY,
        "What is the main research question or hypothesis of this paper?",
        "What methodology did the authors use?",
        "What are the key findings and conclusions?",
        "What are the limitations of this study?",
        "How does this paper relate to other work in the field?",
    ];

    const starterQuestions = useMemo(() => {
        if (paperData?.starter_questions && paperData.starter_questions.length > 0) {
            return paperData.starter_questions;
        }
        return defaultStarterQuestions;
    }, [paperData?.starter_questions]);


    const chatLoadingMessages = [
        "Thinking about your question...",
        "Analyzing the paper...",
        "Gathering citations...",
        "Double-checking references...",
        "Formulating a response...",
        "Verifying information...",
        "Crafting insights...",
        "Synthesizing findings...",
    ]

    const fetchMoreMessages = useCallback(async () => {
        if (!conversationId) {
            return;
        }

        if (!hasMoreMessages || isLoadingMoreMessages) {
            if (!isLoadingMoreMessages && isFetchingHistory) {
                setIsFetchingHistory(false);
            }
            return;
        }

        const gen = fetchGenRef.current;  // capture generation at start
        const isFirstPage = pageNumberConversationHistory === 1;
        setIsLoadingMoreMessages(true);
        try {
            const response = await fetchFromApi(`/api/conversation/${conversationId}?page=${pageNumberConversationHistory}`, {
                method: 'GET',
            });

            // Discard if conversation changed while fetching
            if (fetchGenRef.current !== gen) return;

            const fetchedMessages = response.messages.map((msg: ChatMessage) => ({
                role: msg.role,
                content: msg.content,
                id: msg.id,
                references: msg.references || {},
                guardResult: msg.guardResult || "",
            }));

            // Capture parentId + children for version navigation
            if (response.conversation?.parentId) {
                setConversationParentId(response.conversation.parentId);
            } else {
                setConversationParentId(null);
            }
            if (response.children) {
                setConversationChildren(response.children.map((c: any) => ({ id: c.id, title: c.title, branchPointIndex: c.branchPointIndex || 0 })));
            } else {
                setConversationChildren([]);
            }
            if (response.conversation?.branchPointIndex != null) {
                setBranchPointIndex(response.conversation.branchPointIndex);
            } else {
                setBranchPointIndex(0);
            }

            if (fetchedMessages.length === 0) {
                setHasMoreMessages(false);
                return;
            }

            // First page: replace (prevents duplicates). Later pages: prepend (older history).
            setMessages(prev => isFirstPage ? fetchedMessages : [...fetchedMessages, ...prev]);

            // Store current scroll position and height
            const container = messagesContainerRef.current;
            const scrollHeight = container?.scrollHeight || 0;

            // Add new messages to the top
            setPageNumberConversationHistory(pageNumberConversationHistory + 1);

            // After the component re-renders with new messages
            setTimeout(() => {
                if (container) {
                    // Scroll to maintain the same relative position
                    const newScrollHeight = container.scrollHeight;
                    container.scrollTop = newScrollHeight - scrollHeight;
                }
            }, 0);
        } catch (error) {
            console.error('Error fetching more messages:', error);
        } finally {
            setIsLoadingMoreMessages(false);
            if (isFetchingHistory) {
                setIsFetchingHistory(false);
            }
        }
    }, [hasMoreMessages, isLoadingMoreMessages, conversationId, pageNumberConversationHistory, isFetchingHistory]);

    // Switch to a different conversation (for tree navigation)
    const switchConversation = useCallback((newConvId: string) => {
        if (String(newConvId) === String(conversationId)) return;
        fetchGenRef.current += 1;  // invalidate any in-flight fetches from old conversation
        setConversationId(newConvId);
        setMessages([]);
        setPageNumberConversationHistory(1);
        setHasMoreMessages(true);
        setConversationParentId(null);
        setConversationChildren([]);
        setBranchPointIndex(0);
    }, [conversationId]);

    // Handle message edit → branch at that point and regenerate
    const handleEditSubmit = useCallback(async (messageIndex: number) => {
        if (!editContent.trim() || !conversationId || isBranching) return;

        setIsBranching(true);
        const editedContent = editContent.trim();
        try {
            // Step 1: Create branch at the edit point (copies prefix messages only)
            const branchResp = await fetchFromApi(`/api/conversation/${conversationId}/branch-at`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    edit_message_index: messageIndex,
                    branch_reason: editedContent.slice(0, 30),
                }),
            });

            const newConvId = branchResp.id;
            if (!newConvId) throw new Error("Branch failed");

            // Step 2: Switch to the new conversation
            fetchGenRef.current += 1;  // discard any in-flight fetches from old conv
            setConversationId(newConvId);
            setMessages([]);
            setPageNumberConversationHistory(1);
            setHasMoreMessages(true);
            setConversationParentId(null);
            setEditingMessageIndex(null);
            setEditContent('');

            // Step 3: Add the edited user message to frontend
            const userMessage: ChatMessage = { role: 'user', content: editedContent };
            setMessages(prev => [...prev, userMessage]);

            // Step 4: Stream AI response (animation only)
            const stream = await fetchStreamFromApi('/api/message/chat/paper', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    user_query: editedContent,
                    conversation_id: newConvId,
                    paper_id: id,
                    user_references: [],
                    llm_provider: selectedModel || undefined,
                }),
            });

            setIsStreaming(true);
            setStreamingChunks([]);
            setStreamingReferences(undefined);

            const reader = stream.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                const chunk = decoder.decode(value, { stream: true });
                buffer += chunk;
                const parts = buffer.split(END_DELIMITER);
                buffer = parts.pop() || '';
                for (const event of parts) {
                    if (!event.trim()) continue;
                    try {
                        const parsedChunk = JSON.parse(event.trim());
                        if (parsedChunk.type === 'content') {
                            setStreamingChunks(prev => [...prev, parsedChunk.content]);
                        } else if (parsedChunk.type === 'references') {
                            setStreamingReferences(parsedChunk.content);
                        }
                    } catch { continue; }
                }
            }

            // Step 5: Stream done — reload complete history from DB
            setMessages([]);
            setPageNumberConversationHistory(1);
            setHasMoreMessages(true);
        } catch (error) {
            console.error('Error branching conversation:', error);
        } finally {
            setIsStreaming(false);
            setIsBranching(false);
        }
    }, [editContent, conversationId, isBranching, switchConversation, id, selectedModel, END_DELIMITER]);


    useEffect(() => {
        if (!paperData) return;

        // Initialize conversation once paper data is available
        async function fetchConversation() {
            let retrievedConversationId = null;
            try {
                const response = await fetchFromApi(`/api/paper/conversation?paper_id=${id}`, {
                    method: 'GET',
                });

                if (response && response.id) {
                    retrievedConversationId = response.id;
                }
                setConversationId(retrievedConversationId);
            } catch (error) {
                console.error('Error fetching conversation ID:', error);

                try {

                    if (!retrievedConversationId) {
                        // If no conversation ID is returned, create a new one
                        const newConversationResponse = await fetchFromApi(`/api/conversation/paper/${id}`, {
                            method: 'POST',
                        });
                        retrievedConversationId = newConversationResponse.id;
                    }

                    setConversationId(retrievedConversationId);
                } catch (error) {
                    console.error('Error fetching conversation:', error);
                }
            }
        }

        fetchConversation();
    }, [paperData, id]);

    useEffect(() => {
        if (user) {
            fetchMoreMessages();
        }
    }, [user, fetchMoreMessages]);

    useEffect(() => {
        // Only fetch data when id is available
        if (!id) return;

        async function fetchAvailableModels() {
            try {
                const response = await fetchFromApi(`/api/message/models`);
                if (response.models && Object.keys(response.models).length > 0) {
                    setAvailableModels(response.models);
                    if (response.default && response.models[response.default]) {
                        setSelectedModel((current) => current || response.default);
                    }
                }
            } catch (error) {
                console.error('Error fetching available models:', error);
            }
        }

        fetchAvailableModels();
    }, [id]);

    const handleScroll = () => {
        if (messagesContainerRef.current?.scrollTop === 0) {
            fetchMoreMessages();
        }
    };

    const scrollToLatestMessage = () => {
        // TODO: Should this be scroll to second to last message / user message instead of latest message? Used for loading from history and loading new message.
        if (messagesContainerRef.current && messages.length > 0) {
            // Find the last message element in the DOM
            const messageElements = messagesContainerRef.current.querySelectorAll('[data-message-index]');
            const lastMessageElement = messageElements[messageElements.length - 1];

            if (lastMessageElement) {
                lastMessageElement.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start' // This positions the element at the top of the viewport
                });
            }
        }
    };

    const transformReferencesToFormat = useCallback((references: string[]) => {
        const citations = references.map((ref, index) => ({
            key: `${index + 1}`,
            reference: ref,
        }));

        return {
            "citations": citations,
        }
    }, []);


    useEffect(() => {
        // When streaming starts, scroll to show the latest message at the top
        if (isStreaming) {
            setTimeout(() => {
                scrollToLatestMessage();
            }, 100);
        }
    }, [isStreaming]);

    // Handle typing effect for loading messages
    useEffect(() => {
        if (!isStreaming) {
            setDisplayedText('');
            setIsTyping(false);
            return;
        }

        const currentMessage = chatLoadingMessages[currentLoadingMessageIndex];
        let charIndex = 0;
        setDisplayedText('');
        setIsTyping(true);

        const typingInterval = setInterval(() => {
            if (charIndex < currentMessage.length) {
                setDisplayedText(currentMessage.slice(0, charIndex + 1));
                charIndex++;
            } else {
                setIsTyping(false);
                clearInterval(typingInterval);
            }
        }, 50); // 50ms per character for smooth typing

        return () => clearInterval(typingInterval);
    }, [isStreaming, currentLoadingMessageIndex]);

    // Cycle through loading messages every 11 seconds
    useEffect(() => {
        if (!isStreaming) return;

        const messageInterval = setInterval(() => {
            setCurrentLoadingMessageIndex((prev) =>
                (prev + 1) % chatLoadingMessages.length
            );
        }, 11000); // 11 seconds

        return () => clearInterval(messageInterval);
    }, [isStreaming]);

    // Reset loading message index when streaming starts
    useEffect(() => {
        if (isStreaming) {
            setCurrentLoadingMessageIndex(0);
        }
    }, [isStreaming]);

    // useCallback to calculate chat credit usage
    const updateCreditUsage = useCallback(() => {
        if (!subscription) {
            setCreditUsage(null);
            return;
        }

        const { chat_credits_used, chat_credits_remaining } = subscription.usage;
        const total = chat_credits_used + chat_credits_remaining;
        const usagePercentage = getChatCreditUsagePercentage(subscription);

        const CHAT_CREDIT_TOAST_KEY = "chat_credit_limit_toast_shown";
        if (isChatCreditAtLimit(subscription) && !sessionStorage.getItem(CHAT_CREDIT_TOAST_KEY)) {
            toast.error("Nice! You've used your chat credits for the week. Upgrade your plan to continue chatting.", {
                duration: 5000,
                action: {
                    label: 'Upgrade',
                    onClick: () => {
                        window.location.href = '/pricing';
                    }
                }
            });
            sessionStorage.setItem(CHAT_CREDIT_TOAST_KEY, "true");
        }

        setCreditUsage({
            used: chat_credits_used,
            remaining: chat_credits_remaining,
            total,
            usagePercentage,
            showWarning: isChatCreditNearLimit(subscription),
            isNearLimit: isChatCreditNearLimit(subscription),
            isCritical: isChatCreditNearLimit(subscription, 95)
        });
    }, [subscription]);

    // Update credit usage whenever subscription changes
    useEffect(() => {
        updateCreditUsage();
    }, [updateCreditUsage]);

    const handleSubmit = useCallback(async (e: FormEvent | null = null) => {
        if (e) {
            e.preventDefault();
        }

        if (!currentMessage.trim() || isStreaming) return;

        setErrorState(null);

        // Add user message to chat
        const userMessage: ChatMessage = { role: 'user', content: currentMessage, references: transformReferencesToFormat(userMessageReferences) };
        setMessages(prev => [...prev, userMessage]);

        const failedUserMessage = currentMessage;

        // Clear input field
        setCurrentMessage('');

        // Clear user message references
        setUserMessageReferences([]);

        // Create placeholder for assistant response
        // setMessages(prev => [...prev, { role: 'assistant', content: '' }]);
        setIsStreaming(true);
        setStreamingChunks([]); // Clear previous chunks
        setStreamingReferences(undefined); // Clear previous references

        const requestBody: ChatRequestBody = {
            user_query: userMessage.content,
            conversation_id: conversationId,
            paper_id: id,
            user_references: userMessageReferences,
        };

        if (selectedModel) {
            requestBody.llm_provider = selectedModel;
        }

        try {
            const stream = await fetchStreamFromApi('/api/message/chat/paper', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requestBody),
            });

            setUserMessageReferences([]);

            const reader = stream.getReader();
            const decoder = new TextDecoder();
            let accumulatedContent = '';
            let guardResult = "";
            let msgId = "";
            let references: Reference | undefined = undefined;
            let buffer = ''; // Buffer to accumulate partial chunks

            // Debug counters
            let chunkCount = 0;
            let contentChunks = 0;
            let referenceChunks = 0;

            while (true) {
                const { done, value } = await reader.read();

                if (done) {
                    // Process any remaining buffer content
                    if (buffer.trim()) {
                        console.warn('Unprocessed buffer at end of stream:', buffer);
                    }
                    break;
                }

                // Decode the chunk and add to buffer
                const chunk = decoder.decode(value, { stream: true });
                buffer += chunk;
                chunkCount++;

                // Split buffer by delimiter and process complete events
                const parts = buffer.split(END_DELIMITER);

                // Keep the last part (potentially incomplete) in the buffer
                buffer = parts.pop() || '';

                // Process all complete parts
                for (const event of parts) {
                    if (!event.trim()) continue;

                    try {
                        // Parse the JSON chunk
                        const parsedChunk = JSON.parse(event.trim());
                        const chunkType = parsedChunk.type;
                        const chunkContent = parsedChunk.content;

                        if (chunkType === 'content') {
                            contentChunks++;

                            // Add this content to our accumulated content
                            accumulatedContent += chunkContent;

                            // Update the message with the new content
                            setStreamingChunks(prev => {
                                const newChunks = [...prev, chunkContent];
                                // Update previous content for animation tracking
                                return newChunks;
                            });
                        }
                        else if (chunkType === 'references') {
                            referenceChunks++;

                            // Store the references
                            references = chunkContent;

                            // Update the message with the references
                            setStreamingReferences(chunkContent);
                        } else if (chunkType === 'done') {
                                guardResult = (parsedChunk.content?.guard_result) || parsedChunk.guard_result || "";
                                msgId = String((parsedChunk.content?.message_id) || parsedChunk.message_id || "");
                            } else if (chunkType === 'error') {
                            console.error('Server error in stream:', chunkContent);
                            throw new Error(`Server error: ${chunkContent}`);
                        } else {
                            console.warn(`Unknown chunk type: ${chunkType}`);
                        }
                    } catch (error) {
                        console.error('Error processing event:', error, 'Raw event:', event);
                        // Continue processing other events rather than breaking
                        continue;
                    }
                }
            }


            // After streaming is complete, add the full message to the state
            if (accumulatedContent) {
                const finalMessage: ChatMessage = {
                    id: msgId || undefined,
                    role: 'assistant',
                    content: accumulatedContent,
                    references: references,
                    guardResult: guardResult,
                };
                setMessages(prev => [...prev, finalMessage]);
            }

            // Refetch subscription data to update credit usage
            try {
                await refetchSubscription();
            } catch (error) {
                console.error('Error refetching subscription:', error);
            }

        } catch (error) {
            console.error('Error during streaming:', error);
            setErrorState({ failedUserMessage });
        } finally {
            setIsStreaming(false);
        }
    }, [currentMessage, isStreaming, conversationId, id, userMessageReferences, selectedModel, transformReferencesToFormat, refetchSubscription]);


    const handleTextareaChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
        setCurrentMessage(e.target.value);
    };

    useEffect(() => {
        if (pendingStarterQuestion) {
            handleSubmit(null);
            setPendingStarterQuestion(null);
        }
    }, [pendingStarterQuestion]);


    // Memoize expensive markdown components to prevent re-renders
    const memoizedOverviewContent = useMemo(() => {
        if (!paperData?.summary) return null;

        if (paperData.summary === 'None') return null;

        return (
            <Markdown
                remarkPlugins={[[remarkMath, { singleDollarTextMath: false }], remarkGfm]}
                rehypePlugins={[rehypeKatex]}
                components={{
                    // Apply the custom component to text nodes
                    p: (props) => <CustomCitationLink
                        {...props}
                        handleCitationClick={handleCitationClickFromSummary}
                        messageIndex={0}
                        // Map summary citations to the citation format
                        citations={
                            paperData.summary_citations?.map(citation => ({
                                key: String(citation.index),
                                reference: citation.text
                            })) || []
                        }
                    />,
                    li: (props) => <CustomCitationLink
                        {...props}
                        handleCitationClick={handleCitationClickFromSummary}
                        messageIndex={0}
                        citations={
                            paperData.summary_citations?.map(citation => ({
                                key: String(citation.index),
                                reference: citation.text
                            })) || []
                        }
                    />,
                    div: (props) => <CustomCitationLink
                        {...props}
                        handleCitationClick={handleCitationClickFromSummary}
                        messageIndex={0}
                        citations={
                            paperData.summary_citations?.map(citation => ({
                                key: String(citation.index),
                                reference: citation.text
                            })) || []
                        }
                    />,
                    td: (props) => <CustomCitationLink
                        {...props}
                        handleCitationClick={handleCitationClickFromSummary}
                        messageIndex={0}
                        citations={
                            paperData.summary_citations?.map(citation => ({
                                key: String(citation.index),
                                reference: citation.text
                            })) || []
                        }
                    />,
                    table: CopyableTable,
                }}
            >
                {paperData.summary}
            </Markdown>
        );
    }, [paperData?.summary, paperData?.summary_citations, handleCitationClickFromSummary]);

    // Memoize message rendering to prevent unnecessary re-renders
    const memoizedMessages = useMemo(() => {
        return messages.map((msg, index) => {
            const isEditing = editingMessageIndex === index;
            const isUser = msg.role === 'user';
            // Show version nav when conversation has a parent and this is the last user message
            const hasParent = !!conversationParentId;
            const isLastUser = isUser && index === messages.map((m, i) => ({ m, i })).filter(x => x.m.role === 'user').pop()?.i;
            const hasChildren = conversationChildren.length > 0;
            // ← button: show at branchPointIndex (where THIS conversation diverged from parent)
            const showBackNav = hasParent && branchPointIndex > 0 && index === branchPointIndex;
            // → button: show at child's branchPointIndex (where child diverged from this conversation)
            const childBranchIndex = hasChildren ? conversationChildren[0].branchPointIndex : 0;
            const showForwardNav = hasChildren && childBranchIndex > 0 && index === childBranchIndex;
            const showVersionNav = showBackNav || showForwardNav;

            return (
            <div
                key={`${msg.id || `msg-${index}`}-${index}-${msg.role}-${msg.content.slice(0, 20).replace(/\s+/g, '')}`}
                className='flex flex-row gap-2 items-end'
            >
                {
                    isUser && user && (
                        <Avatar className="h-6 w-6">
                            <AvatarImage src={user.picture} alt={user.name || user.email} />
                            <AvatarFallback className={getAlphaHashToBackgroundColor(user.name || user.email)}>
                                {getInitials(user.name || user.email)}
                            </AvatarFallback>
                        </Avatar>
                    )
                }
                <div
                    data-message-index={index}
                    className={`relative group prose dark:prose-invert p-2 !max-w-full rounded-lg ${isUser
                        ? 'bg-blue-200 text-blue-800 w-fit animate-fade-in min-w-[120px]'
                        : 'w-full text-primary'
                        }`}
                >
                    {isEditing ? (
                        /* Edit mode */
                        <div className="flex flex-col gap-2">
                            <Textarea
                                value={editContent}
                                onChange={(e) => setEditContent(e.target.value)}
                                className="min-w-[300px] text-sm resize-none border-blue-300 dark:border-blue-700 bg-white dark:bg-gray-800"
                                autoFocus
                                rows={3}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter' && !e.shiftKey) {
                                        e.preventDefault();
                                        handleEditSubmit(index);
                                    }
                                    if (e.key === 'Escape') {
                                        setEditingMessageIndex(null);
                                        setEditContent('');
                                    }
                                }}
                            />
                            <div className="flex items-center gap-2 justify-end">
                                <Button
                                    size="sm"
                                    variant="ghost"
                                    className="h-7 text-xs"
                                    onClick={() => { setEditingMessageIndex(null); setEditContent(''); }}
                                >
                                    取消
                                </Button>
                                <Button
                                    size="sm"
                                    variant="default"
                                    className="h-7 text-xs bg-blue-500 hover:bg-blue-400"
                                    onClick={() => handleEditSubmit(index)}
                                    disabled={!editContent.trim() || isBranching}
                                >
                                    {isBranching ? <Loader className="animate-spin size-3" /> : <ArrowUp className="size-3" />}
                                    发送
                                </Button>
                            </div>
                        </div>
                    ) : (
                        /* Normal display */
                        <>
                            <Markdown
                                remarkPlugins={[[remarkMath, { singleDollarTextMath: false }], remarkGfm]}
                                rehypePlugins={[rehypeKatex]}
                                components={{
                                    p: ({children, ...props}: any) => <CitationWrapper children={children} handleCitationClick={handleCitationClick} messageIndex={index} />,
                                    li: ({children, ...props}: any) => <CitationWrapper children={children} handleCitationClick={handleCitationClick} messageIndex={index} />,
                                    h2: ({children, ...props}: any) => React.createElement('h2', null, <CitationWrapper children={children} handleCitationClick={handleCitationClick} messageIndex={index} />),
                                    h3: ({children, ...props}: any) => React.createElement('h3', null, <CitationWrapper children={children} handleCitationClick={handleCitationClick} messageIndex={index} />),
                                    h4: ({children, ...props}: any) => React.createElement('h4', null, <CitationWrapper children={children} handleCitationClick={handleCitationClick} messageIndex={index} />),
                                    table: CopyableTable,
                                }}>
                                {msg.content}
                            </Markdown>
                            {/* Edit button + Version nav for user messages */}
                            {isUser && (
                                <div className="flex items-center gap-1 mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
                                    {showBackNav && (
                                        <Button
                                            size="sm"
                                            variant="ghost"
                                            className="h-5 w-5 p-0"
                                            title="回到父对话"
                                            onClick={() => conversationParentId && switchConversation(conversationParentId)}
                                        >
                                            <ChevronLeft className="size-3" />
                                        </Button>
                                    )}
                                    {showForwardNav && (
                                        <Button
                                            size="sm"
                                            variant="ghost"
                                            className="h-5 w-5 p-0"
                                            title="到子对话"
                                            onClick={() => hasChildren && switchConversation(conversationChildren[0].id)}
                                        >
                                            <ChevronRight className="size-3" />
                                        </Button>
                                    )}
                                    <Button
                                        size="sm"
                                        variant="ghost"
                                        className="h-5 px-1 text-xs text-muted-foreground hover:text-foreground"
                                        onClick={() => {
                                            setEditingMessageIndex(index);
                                            setEditContent(msg.content);
                                        }}
                                    >
                                        <Pencil className="size-3 mr-0.5" />
                                        编辑
                                    </Button>
                                </div>
                            )}
                        </>
                    )}
                    {msg.references && msg.references.citations && msg.references.citations.length > 0 && (
                            <div>
                                <div className="mt-0 pt-0 border-t border-gray-300 dark:border-gray-700 flex justify-between items-center" id="references-section">
                                    <h4 className="text-sm font-semibold">References</h4>
                                </div>
                                <ul className="list-none p-0">
                                    {msg.references.citations.map((value, refIndex) => (
                                        <div
                                            key={refIndex}
                                            className={`flex flex-row gap-2 animate-fade-in ${matchesCurrentCitation(value.key, index) ? 'bg-blue-100 dark:bg-blue-900 rounded p-1 transition-colors duration-300' : ''}`}
                                            id={`citation-${value.key}-${index}`}
                                            onClick={() => handleCitationClick(value.key, index)}
                                        >
                                            <div className={`text-xs ${isUser
                                                ? 'bg-blue-200 text-blue-800'
                                                : 'text-secondary-foreground'
                                                }`}>
                                                <a href={`#citation-ref-${value.key}`}>{value.key}</a>
                                            </div>
                                            <div
                                                id={`citation-ref-${value.key}-${index}`}
                                                className={`text-xs ${isUser
                                                    ? 'bg-blue-200 text-blue-800 line-clamp-1'
                                                    : 'text-secondary-foreground'
                                                    }`}
                                            >
                                                {value.reference}
                                            </div>
                                        </div>
                                    ))}
                                </ul>
                            </div>
                        )}
                        {msg.role === "assistant" && (
                          <div className="flex items-center gap-2 mt-1">
                            <ChatMessageActions message={msg.content} references={msg.references} />
                            {msg.guardResult && <GuardSummaryBar guardInfo={parseGuardResult(msg.guardResult)} />}
                            <FeedbackButtons messageId={msg.id} />
                          </div>
                        )}
                </div>
            </div>
        )});
    }, [messages, user, handleCitationClick, handleCitationClickFromSummary, matchesCurrentCitation, editingMessageIndex, editContent, isBranching, conversationParentId, switchConversation, handleEditSubmit, isStreaming]);

    useEffect(() => {
        const date = new Date();
        date.setDate(date.getDate() + (1 + 7 - date.getDay()) % 7);
        setNextMonday(date);
    }, []);

    const heightClass = isMobile ? "h-[calc(100vh-128px)]" : "h-[calc(100vh-64px)]";

    return (
        <>
            {
                rightSideFunction !== 'Read' && (
                    <div className="flex-grow h-full overflow-hidden pr-[60px]">
                        {
                            rightSideFunction === 'Annotations' && user && (
                                <div className={`flex flex-col ${heightClass} overflow-y-auto`}>
                                    <AnnotationsView
                                        annotations={annotations}
                                        highlights={highlights}
                                        user={user}
                                        onHighlightClick={handleHighlightClick}
                                        activeHighlight={activeHighlight}
                                        renderedHighlightPositions={renderedHighlightPositions}
                                        composeHighlightId={composeHighlightId}
									updateAnnotation={updateAnnotation}
                                        onComposeHighlightDismiss={onComposeHighlightDismiss}
                                        addAnnotation={addAnnotation}
                                    />
                                </div>
                            )
                        }
                        {
                            rightSideFunction === 'Share' && paperData && (
                                <div className={`flex flex-col ${heightClass} p-4 space-y-4`}>
                                    <h3 className="text-lg font-semibold">Share Paper</h3>
                                    {paperData.share_id ? (
                                        <div className="space-y-3">
                                            <p className="text-sm text-muted-foreground">This paper is currently public. Anyone with the link can view it.</p>
                                            <div className="flex items-center space-x-2">
                                                <Input
                                                    readOnly
                                                    value={`${window.location.origin}/paper/share/${paperData.share_id}`}
                                                    className="flex-1"
                                                />
                                                <Button
                                                    variant="outline"
                                                    size="sm"
                                                    onClick={async () => {
                                                        await navigator.clipboard.writeText(`${window.location.origin}/paper/share/${paperData.share_id}`);
                                                        toast.success("Link copied!");
                                                    }}
                                                >
                                                    Copy Link
                                                </Button>
                                            </div>
                                            <Button
                                                variant="destructive"
                                                onClick={handleUnshare}
                                                disabled={isSharing}
                                                className="w-fit"
                                            >
                                                {isSharing ? <Loader className="animate-spin mr-2 h-4 w-4" /> : null}
                                                <LockIcon /> Make Private
                                            </Button>
                                        </div>
                                    ) : (
                                        <div className="space-y-3">
                                            <p className="text-sm text-muted-foreground">Make this paper public to share it with others via a unique link. All of your <b>annotations and chats</b> will be visible to anyone with the link.</p>
                                            <Button
                                                onClick={handleShare}
                                                disabled={isSharing}
                                                className="w-fit"
                                            >
                                                {isSharing ? <Loader className="animate-spin mr-2 h-4 w-4" /> : null}
                                                <Share2Icon /> Share
                                            </Button>
                                        </div>
                                    )}
                                </div>
                            )
                        }
                        {
                            rightSideFunction === 'Overview' && paperData.summary && (
                                <div className={`flex flex-col ${heightClass} md:px-2 overflow-y-auto m-2 relative animate-fade-in`}>
                                    {/* Paper Metadata Section */}
                                    <div className="prose dark:prose-invert !max-w-full text-sm">
                                        {paperData.title && (
                                            <h1 className="text-2xl font-bold">{paperData.title}</h1>
                                        )}
                                        {memoizedOverviewContent}
                                        {
                                            paperData.summary_citations && paperData.summary_citations.length > 0 && (
                                                <div className="mt-0 pt-0 border-t border-gray-300 dark:border-gray-700" id="references-section">
                                                    <h4 className="text-sm font-semibold mb-2">References</h4>
                                                    <ul className="list-none p-0">
                                                        {paperData.summary_citations.map((citation, index) => (
                                                            <div
                                                                key={index}
                                                                className={`flex flex-row gap-2 ${matchesCurrentCitation(`${citation.index}`, 0) ? 'bg-blue-100 dark:bg-blue-900 rounded p-1 transition-colors duration-300' : ''}`}
                                                                id={`citation-${citation.index}-${index}`}
                                                                onClick={() => handleCitationClickFromSummary(`${citation.index}`, 0)}
                                                            >
                                                                <div className={`text-xs text-secondary-foreground`}>
                                                                    <span>{citation.index}</span>
                                                                </div>
                                                                <div
                                                                    id={`citation-ref-${citation.index}-${index}`}
                                                                    className={`text-xs text-secondary-foreground
                                                    `}>
                                                                    {citation.text}
                                                                </div>
                                                            </div>
                                                        ))}
                                                    </ul>
                                                </div>
                                            )}
                                        <div className="sticky bottom-4 right-4 flex justify-end">
                                            <Button
                                                variant="default"
                                                className="w-fit bg-blue-500 hover:bg-blue-400 dark:hover:bg-blue-600 cursor-pointer z-10 shadow-md"
                                                onClick={() => {
                                                    setRightSideFunction('Chat');
                                                }}
                                            >
                                                <Sparkle className="mr-1" />
                                                Ask a Question
                                            </Button>
                                        </div>
                                    </div>
                                </div>
                            )
                        }
                        {
                            rightSideFunction === 'Chat' && (
                                <div className={`flex flex-col ${heightClass} overflow-y-auto relative`}>
                                    <PaperMetadata paperData={paperData} />
                                    <BranchDirectory
                                        paperId={id}
                                        activeConversationId={conversationId}
                                        onSwitchConversation={switchConversation}
                                    />
                                    {/* Paper Chat Section */}
                                    <div
                                        className={`flex-1 overflow-y-auto space-y-2 transition-all duration-300 mt-2 ease-in-out ${isStreaming ? 'pb-24' : ''}`}
                                        ref={messagesContainerRef}
                                        onScroll={handleScroll}
                                    >
                                        {hasMoreMessages && messages.length > 0 && !isFetchingHistory && (
                                            <div className="text-center py-2">
                                                {isLoadingMoreMessages ? (
                                                    <div className="text-sm text-gray-500">Loading messages...</div>
                                                ) : (
                                                    <button
                                                        className="text-sm text-blue-500 hover:text-blue-700"
                                                        onClick={fetchMoreMessages}
                                                    >
                                                        Load earlier messages
                                                    </button>
                                                )}
                                            </div>
                                        )}
                                        {isFetchingHistory ? <ChatHistorySkeleton /> :
                                            (
                                                <>

                                                    {memoizedMessages}

                                                </>
                                            )
                                        }
                                        {errorState && !isStreaming && (
                                            <div className="relative group prose dark:prose-invert p-2 !max-w-full rounded-lg w-full text-primary dark:text-primary-foreground">
                                                <div className="text-red-500">
                                                    <p>An error occurred while processing your request.</p>
                                                    <Button
                                                        variant="outline"
                                                        className="mt-2"
                                                        onClick={() => {
                                                            const lastUserMessageIndex = messages.findLastIndex(m => m.role === 'user');
                                                            if (lastUserMessageIndex !== -1) {
                                                                setMessages(prev => prev.slice(0, lastUserMessageIndex));
                                                            }
                                                            setCurrentMessage(errorState.failedUserMessage);
                                                            setErrorState(null);
                                                            inputMessageRef.current?.focus();
                                                        }}
                                                    >
                                                        Try Again
                                                    </Button>
                                                </div>
                                            </div>
                                        )}
                                        {
                                            isStreaming && streamingChunks.length > 0 && (
                                                <div className="relative group prose dark:prose-invert p-2 !max-w-full rounded-lg w-full text-primary">
                                                    <AnimatedMarkdown
                                                        content={streamingChunks.join('')}
                                                        remarkPlugins={[[remarkMath, { singleDollarTextMath: false }], remarkGfm]}
                                                        rehypePlugins={[rehypeKatex]}
                                                        components={{
                                                            // Apply the custom component to text nodes
                                                            p: (props) => <CustomCitationLink
                                                                {...props}
                                                                handleCitationClick={handleCitationClick}
                                                                messageIndex={messages.length} // Use the next message index
                                                                citations={streamingReferences?.citations || []}
                                                            />,
                                                            li: (props) => <CustomCitationLink
                                                                {...props}
                                                                handleCitationClick={handleCitationClick}
                                                                messageIndex={messages.length} // Use the next message index
                                                                citations={streamingReferences?.citations || []}
                                                            />,
                                                            div: (props) => <CustomCitationLink
                                                                {...props}
                                                                handleCitationClick={handleCitationClick}
                                                                messageIndex={messages.length} // Use the next message index
                                                                citations={streamingReferences?.citations || []}
                                                            />,
                                                            td: (props) => <CustomCitationLink
                                                                {...props}
                                                                handleCitationClick={handleCitationClickFromSummary}
                                                                messageIndex={0}
                                                                citations={streamingReferences?.citations || []}
                                                            />,
                                                            table: CopyableTable,
                                                        }}
                                                    />
                                                    {streamingReferences && streamingReferences.citations && streamingReferences.citations.length > 0 && (
                                                        <div
                                                            className="mt-0 pt-0 border-t border-gray-300 dark:border-gray-700 flex justify-between items-center"
                                                            id="references-section"
                                                        >
                                                            <h4 className="text-sm font-semibold">References</h4>
                                                            <ChatMessageActions
                                                                message={streamingChunks.join('')}
                                                                references={streamingReferences}
                                                            />
                                                        </div>
                                                    )}
                                                </div>
                                            )
                                        }
                                        {
                                            isStreaming && (
                                                <div className="flex items-center gap-3 p-0">
                                                    <Loader className="animate-spin w-6 h-6 text-blue-500 flex-shrink-0" />
                                                    <div className="text-sm text-secondary-foreground p-0">
                                                        {displayedText}
                                                        {isTyping && (
                                                            <span className="animate-pulse">|</span>
                                                        )}
                                                    </div>
                                                </div>
                                            )
                                        }
                                        <div ref={messagesEndRef} />
                                    </div>
                                    {(messages.length === 0 || messages.length === 1) && !hasMoreMessages && (
                                        <div className="text-center text-gray-500 my-4">
                                            <div className='flex overflow-x-auto gap-2 mt-2 pb-2 scrollbar-hide'>
                                                {starterQuestions.slice(0, 5).map((question, i) => {
                                                    const messageToSend = question === COMPREHENSIVE_OVERVIEW_DISPLAY
                                                        ? COMPREHENSIVE_OVERVIEW_PROMPT
                                                        : question;
                                                    return (
                                                        <Button
                                                            key={i}
                                                            variant="outline"
                                                            className="text-sm font-normal p-2 bg-background text-secondary-foreground hover:bg-secondary/50 border rounded-full whitespace-nowrap"
                                                            onClick={() => {
                                                                setCurrentMessage(messageToSend);
                                                                inputMessageRef.current?.focus();
                                                                chatInputFormRef.current?.scrollIntoView({
                                                                    behavior: 'smooth',
                                                                    block: 'nearest',
                                                                    inline: 'nearest',
                                                                });
                                                                setPendingStarterQuestion(messageToSend);
                                                            }}
                                                        >
                                                            {question}
                                                        </Button>
                                                    );
                                                })}
                                            </div>
                                        </div>
                                    )}
                                    <form onSubmit={handleSubmit} className="flex flex-col gap-2" ref={chatInputFormRef}>
                                        {
                                            userMessageReferences.length > 0 && (
                                                <div className='flex flex-row gap-2'>
                                                    {userMessageReferences.map((ref, index) => (
                                                        <div key={index} className="text-xs text-secondary-foreground flex bg-secondary p-2 rounded-lg">
                                                            <p
                                                                className='
                                                                    overflow-hidden
                                                                    text-ellipsis
                                                                    whitespace-normal
                                                                    max-w-[200px]
                                                                    text-secondary-foreground
                                                                    line-clamp-2
                                                                    '
                                                                onClick={() =>
                                                                    setExplicitSearchTerm(ref)
                                                                }
                                                            >
                                                                {ref}
                                                            </p>
                                                            <Button
                                                                variant='ghost'
                                                                className='h-auto w-fit p-0 !px-0'
                                                                onClick={() =>
                                                                    setUserMessageReferences(prev => prev.filter((_, i) => i !== index))
                                                                }
                                                            >
                                                                <X size={2} />
                                                            </Button>
                                                        </div>
                                                    ))}
                                                </div>
                                            )
                                        }
                                        <div
                                            className='rounded-md p-0.5 flex flex-col gap-2 bg-secondary'
                                        >
                                            {/* User message input area */}
                                            <Textarea
                                                value={currentMessage}
                                                onChange={handleTextareaChange}
                                                ref={inputMessageRef}
                                                placeholder="Ask something about this paper."
                                                className="border-none bg-secondary dark:bg-secondary rounded-md resize-none hover:resize-y p-2 focus-visible:outline-none focus-visible:ring-0 shadow-none min-h-[2rem] max-h-32"
                                                disabled={isStreaming || (creditUsage?.usagePercentage ?? 0) >= 100}
                                                onKeyDown={(e) => {
                                                    if (e.key === 'Enter' && !e.shiftKey) {
                                                        e.preventDefault();
                                                        handleSubmit(null);
                                                    }
                                                }}
                                            />
                                            <div className="flex flex-row justify-between gap-2">
                                                <div className="flex flex-row gap-2">
                                                    <DropdownMenu>
                                                        <DropdownMenuTrigger asChild>
                                                            <Button
                                                                variant="ghost"
                                                                className="w-fit text-sm gap-1.5"
                                                                title='Settings - Configure chat model'
                                                                disabled={isStreaming}
                                                            >
                                                                <Route
                                                                    className="h-4 w-4 text-secondary-foreground"
                                                                />
                                                                {selectedModel && availableModels[selectedModel] && (
                                                                    <span className="text-xs text-secondary-foreground truncate max-w-[10rem]">
                                                                        {availableModels[selectedModel]}
                                                                    </span>
                                                                )}
                                                            </Button>
                                                        </DropdownMenuTrigger>
                                                        <DropdownMenuContent className="w-56">
                                                            <DropdownMenuSub>
                                                                <DropdownMenuSubTrigger className="flex items-center">
                                                                    <Sparkle className="mr-2 h-4 w-4" />
                                                                    <span className="flex-1">Model {selectedModel ? `(${availableModels[selectedModel]})` : ''}</span>
                                                                    {subscription && subscription.plan !== 'researcher' && (
                                                                        <LockIcon className="ml-2 h-3 w-3 text-muted-foreground" />
                                                                    )}
                                                                </DropdownMenuSubTrigger>
                                                                <DropdownMenuSubContent>
                                                                    {subscription && subscription.plan !== 'researcher' ? (
                                                                        <>
                                                                            {Object.entries(availableModels).map(([modelKey, modelName]) => (
                                                                                <DropdownMenuItem
                                                                                    key={modelKey}
                                                                                    onClick={() => {
                                                                                        window.location.href = '/pricing';
                                                                                    }}
                                                                                    className="flex items-center justify-between text-muted-foreground"
                                                                                >
                                                                                    <span>{modelName}</span>
                                                                                    <LockIcon className="h-3 w-3" />
                                                                                </DropdownMenuItem>
                                                                            ))}
                                                                            <DropdownMenuItem
                                                                                onClick={() => {
                                                                                    window.location.href = '/pricing';
                                                                                }}
                                                                                className="flex items-center justify-center mt-1 bg-blue-500 text-white focus:bg-blue-400 focus:text-white font-medium"
                                                                            >
                                                                                Upgrade to select models
                                                                            </DropdownMenuItem>
                                                                        </>
                                                                    ) : (
                                                                        Object.entries(availableModels).map(([modelKey, modelName]) => (
                                                                            <DropdownMenuItem
                                                                                key={modelKey}
                                                                                onClick={() => {
                                                                                    setSelectedModel(modelKey);
                                                                                    setRightSideFunction('Chat');
                                                                                }}
                                                                                className="flex items-center justify-between"
                                                                            >
                                                                                <span>{modelName}</span>
                                                                                {modelKey === selectedModel && (
                                                                                    <Check className="h-4 w-4 text-green-500" />
                                                                                )}
                                                                            </DropdownMenuItem>
                                                                        ))
                                                                    )}
                                                                </DropdownMenuSubContent>
                                                            </DropdownMenuSub>
                                                        </DropdownMenuContent>
                                                    </DropdownMenu>
                                                </div>
                                                <Button
                                                    type="submit"
                                                    onKeyDown={(e) => {
                                                        if (e.key === 'Enter' && !e.shiftKey) {
                                                            e.preventDefault();
                                                            handleSubmit(null);
                                                        }
                                                    }}
                                                    variant="default"
                                                    className="w-fit rounded-full h-fit !px-2 py-2 bg-blue-500 hover:bg-blue-400"
                                                    disabled={isStreaming}
                                                >
                                                    <ArrowUp
                                                        className="h-4 w-4 rounded-full"
                                                        aria-hidden="true"
                                                    />
                                                </Button>
                                            </div>
                                        </div>
                                        {/* Chat Credit Usage Display */}
                                        {creditUsage && creditUsage.showWarning && (
                                            <div className={`text-xs px-2 py-1 ${creditUsage.isCritical ? 'text-red-600 dark:text-red-400' : 'text-amber-600 dark:text-amber-400'} justify-between flex`}>
                                                <div className="font-semibold">{creditUsage.used} credits used</div>
                                                <div className="font-semibold">
                                                    <HoverCard>
                                                        <HoverCardTrigger asChild>
                                                            <span>{creditUsage.remaining} credits remaining</span>
                                                        </HoverCardTrigger>
                                                        <HoverCardContent side="top" className="w-48">
                                                            <p className="text-sm">Resets on {nextMonday.toLocaleDateString()}</p>
                                                        </HoverCardContent>
                                                    </HoverCard>
                                                    <Link
                                                        href="/pricing"
                                                        className="text-blue-500 hover:text-blue-700 ml-1"
                                                    >
                                                        Upgrade
                                                    </Link>
                                                </div>
                                            </div>
                                        )}
                                    </form>
                                </div>
                            )
                        }
                        {
                            rightSideFunction === 'Notes' && (
                                <div className={`flex flex-col ${heightClass} overflow-hidden`}>
                                    <NotesPanel
                                        paperId={id}
                                        paperTitle={paperData.title}
                                    />
                                </div>
                            )
                        }
                        {
                            rightSideFunction === 'Parsed' && (
                                <div className={`flex flex-col ${heightClass} overflow-hidden`}>
                                    <ParsedPanel
                                        paperId={id}
                                        paperTitle={paperData.title}
                                    />
                                </div>
                            )
                        }
                    </div>
                )
            }
        </>
    )
}
