"use client"

import { createContext, useContext, useState, useEffect, ReactNode } from 'react';

export interface BasicUser {
    name: string;
    picture: string;
    id?: string;
}

export interface User extends BasicUser {
    id: string;
    email: string;
    is_active: boolean;
    is_blocked: boolean;
}

interface AuthContextType {
    user: User | null;
    loading: boolean;
    error: string | null;
    login: () => Promise<void>;
    logout: (allDevices?: boolean) => Promise<void>;
}

const LOCAL_USER: User = {
    id: "local",
    name: "Local User",
    email: "user@local",
    picture: "",
    is_active: true,
    is_blocked: false,
};

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
    const [user, setUser] = useState<User | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        // No-auth mode: immediately set local user
        setUser(LOCAL_USER);
        setLoading(false);
    }, []);

    const login = async () => {
        setUser(LOCAL_USER);
    };

    const logout = async (_allDevices = false) => {
        // No-op in local mode — user stays logged in
    };

    return (
        <AuthContext.Provider value={{ user, loading, error, login, logout }}>
            {children}
        </AuthContext.Provider>
    );
}

export function useAuth() {
    const context = useContext(AuthContext);
    if (context === undefined) {
        throw new Error('useAuth must be used within an AuthProvider');
    }
    return context;
}
