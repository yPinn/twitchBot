-- =============================================================================
-- Niibot Database Schema
-- =============================================================================

-- Update timestamp trigger function (shared by all tables)
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- =============================================================================
-- OAuth Tokens Management
-- =============================================================================

-- Tokens table for storing OAuth tokens
CREATE TABLE IF NOT EXISTS tokens (
    user_id TEXT PRIMARY KEY,
    token TEXT NOT NULL,
    refresh TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_tokens_user_id ON tokens(user_id);

-- Create trigger for automatic updated_at updates
DROP TRIGGER IF EXISTS update_tokens_updated_at ON tokens;
CREATE TRIGGER update_tokens_updated_at
    BEFORE UPDATE ON tokens
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- Multi-Channel Management
-- =============================================================================

-- Channels table for managing monitored channels
CREATE TABLE IF NOT EXISTS channels (
    id SERIAL PRIMARY KEY,
    channel_id TEXT NOT NULL,
    channel_name TEXT NOT NULL,
    is_active BOOLEAN DEFAULT true,
    added_by TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(channel_id)
);

-- Channel settings table for per-channel configuration
CREATE TABLE IF NOT EXISTS channel_settings (
    channel_id TEXT PRIMARY KEY REFERENCES channels(channel_id) ON DELETE CASCADE,
    prefix TEXT DEFAULT '!',
    settings JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_channels_channel_id ON channels(channel_id);
CREATE INDEX IF NOT EXISTS idx_channels_is_active ON channels(is_active);
CREATE INDEX IF NOT EXISTS idx_channel_settings_channel_id ON channel_settings(channel_id);

-- Create triggers for automatic updated_at updates
DROP TRIGGER IF EXISTS update_channels_updated_at ON channels;
CREATE TRIGGER update_channels_updated_at
    BEFORE UPDATE ON channels
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_channel_settings_updated_at ON channel_settings;
CREATE TRIGGER update_channel_settings_updated_at
    BEFORE UPDATE ON channel_settings
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- Views for monitoring and debugging
-- =============================================================================

-- Token status view
CREATE OR REPLACE VIEW token_status AS
SELECT 
    user_id,
    CASE 
        WHEN LENGTH(token) > 0 THEN 'Active'
        ELSE 'Inactive'
    END as status,
    created_at,
    updated_at
FROM tokens;

-- Active channels view
CREATE OR REPLACE VIEW active_channels AS
SELECT 
    c.channel_id,
    c.channel_name,
    c.added_by,
    cs.prefix,
    cs.settings,
    c.created_at
FROM channels c
LEFT JOIN channel_settings cs ON c.channel_id = cs.channel_id
WHERE c.is_active = true
ORDER BY c.created_at;

-- =============================================================================
-- Custom Commands System
-- =============================================================================

-- Custom commands table for per-channel command definitions
CREATE TABLE IF NOT EXISTS custom_commands (
    id SERIAL PRIMARY KEY,
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE CASCADE,
    command_name TEXT NOT NULL,
    response_text TEXT NOT NULL,
    cooldown_seconds INTEGER DEFAULT 5,
    user_level TEXT DEFAULT 'everyone', -- everyone, subscriber, mod, owner
    is_active BOOLEAN DEFAULT true,
    usage_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(channel_id, command_name)
);

-- Command usage tracking for cooldown management
CREATE TABLE IF NOT EXISTS command_usage (
    channel_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    command_name TEXT NOT NULL,
    last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(channel_id, user_id, command_name)
);

-- Indexes for performance optimization
CREATE INDEX IF NOT EXISTS idx_custom_commands_channel_active ON custom_commands(channel_id, is_active);
CREATE INDEX IF NOT EXISTS idx_custom_commands_name ON custom_commands(command_name);
CREATE INDEX IF NOT EXISTS idx_command_usage_lookup ON command_usage(channel_id, user_id, command_name);
CREATE INDEX IF NOT EXISTS idx_command_usage_time ON command_usage(last_used);

-- Trigger for automatic updated_at updates
DROP TRIGGER IF EXISTS update_custom_commands_updated_at ON custom_commands;
CREATE TRIGGER update_custom_commands_updated_at
    BEFORE UPDATE ON custom_commands
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- Channel Points System (for + Niibot redemption records only)
-- =============================================================================

-- Simplified version: record + Niibot redemption history only
CREATE TABLE IF NOT EXISTS niibot_redemptions (
    id SERIAL PRIMARY KEY,
    channel_id TEXT NOT NULL,       -- Channel where redemption occurred
    requester_name TEXT NOT NULL,   -- Name of the requester
    target_channel TEXT NOT NULL,   -- Target channel to add
    cost INTEGER DEFAULT 0,         -- Redemption cost
    success BOOLEAN DEFAULT false,  -- Whether execution was successful
    error_message TEXT,             -- Error reason if failed
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for performance and history queries
CREATE INDEX IF NOT EXISTS idx_niibot_redemptions_channel ON niibot_redemptions(channel_id);
CREATE INDEX IF NOT EXISTS idx_niibot_redemptions_target ON niibot_redemptions(target_channel);
CREATE INDEX IF NOT EXISTS idx_niibot_redemptions_time ON niibot_redemptions(created_at);

