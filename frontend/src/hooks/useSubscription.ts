// useSubscription hook — PaperBridge local mode: everything unlimited.

import { useState, useEffect, useCallback } from 'react';
import { SubscriptionData, UseSubscriptionReturn } from '@/lib/schema';

const HUGE = 1_000_000_000;
const FAKE_UNLIMITED: SubscriptionData = {
    plan: "researcher",
    limits: {
        paper_uploads: HUGE,
        knowledge_base_size: HUGE,
        chat_credits_weekly: HUGE,
        audio_overviews_weekly: HUGE,
        data_tables_weekly: HUGE,
        discover_searches_weekly: HUGE,
        projects: HUGE,
        model: ["claude-sonnet-4-6", "deepseek-chat", "gpt-4o-mini"],
    },
    usage: {
        paper_uploads: 0,
        paper_uploads_remaining: HUGE,
        knowledge_base_size: 0,
        knowledge_base_size_remaining: HUGE,
        chat_credits_used: 0,
        chat_credits_remaining: HUGE,
        audio_overviews_used: 0,
        audio_overviews_remaining: HUGE,
        projects: 0,
        projects_remaining: HUGE,
        data_tables_used: 0,
        data_tables_remaining: HUGE,
        discover_searches_used: 0,
        discover_searches_remaining: HUGE,
    },
};

export const useSubscription = (): UseSubscriptionReturn => {
    const [subscription] = useState<SubscriptionData | null>(FAKE_UNLIMITED);
    const [loading] = useState<boolean>(false);
    const [error] = useState<string | null>(null);

    const fetchSubscription = useCallback(async () => {}, []);

    return { subscription, loading, error, refetch: fetchSubscription };
};

// All helpers return "not at limit" / 0% usage
type SubOrNull = SubscriptionData | null;
export const getStorageUsagePercentage = (_: SubOrNull) => 0;
export const getPaperUploadPercentage = (_: SubOrNull) => 0;
export const getChatCreditUsagePercentage = (_: SubOrNull) => 0;
export const getAudioOverviewUsagePercentage = (_: SubOrNull) => 0;
export const getProjectUsagePercentage = (_: SubOrNull) => 0;
export const getDataTableUsagePercentage = (_: SubOrNull) => 0;
export const getDiscoverSearchUsagePercentage = (_: SubOrNull) => 0;
export const isStorageAtLimit = (_: SubOrNull) => false;
export const isPaperUploadAtLimit = (_: SubOrNull) => false;
export const isStorageNearLimit = (_: SubOrNull, _threshold?: number) => false;
export const isPaperUploadNearLimit = (_: SubOrNull, _threshold?: number) => false;
export const isChatCreditAtLimit = (_: SubOrNull) => false;
export const isChatCreditNearLimit = (_: SubOrNull, _threshold?: number) => false;
export const isAudioOverviewAtLimit = (_: SubOrNull) => false;
export const isAudioOverviewNearLimit = (_: SubOrNull, _threshold?: number) => false;
export const isProjectAtLimit = (_: SubOrNull) => false;
export const isProjectNearLimit = (_: SubOrNull, _threshold?: number) => false;
export const isDiscoverSearchAtLimit = (_: SubOrNull) => false;
export const isDiscoverSearchNearLimit = (_: SubOrNull, _threshold?: number) => false;
export const isDataTableNearLimit = (_: SubOrNull, _threshold?: number) => false;
export const isDataTableAtLimit = (_: SubOrNull) => false;

// Compute next Monday as a Date value (used directly as `nextMonday.toLocaleDateString()`)
const _nextMonday = new Date();
_nextMonday.setDate(_nextMonday.getDate() + ((1 + 7 - _nextMonday.getDay()) % 7 || 7));
_nextMonday.setHours(0, 0, 0, 0);
export const nextMonday: Date = _nextMonday;
export const formatFileSize = (bytes: number) => {
    if (bytes === 0) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return (bytes / Math.pow(1024, i)).toFixed(1) + " " + units[i];
};
