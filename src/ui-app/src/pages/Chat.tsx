import React, { useState, useEffect, useRef } from 'react';
import { Box, Typography, Paper, TextField, Button, List, ListItem, ListItemText, CircularProgress } from '@mui/material';
import SendIcon from '@mui/icons-material/Send';
import apiClient from '../api/client';
import { useAuthContext } from '../contexts/AuthContext';

interface Message {
  id: number;
  text: string;
  sender: 'user' | 'bot';
}

const WELCOME_MSG: Message = {
  id: 0,
  text: "Hello! I'm your AI financial assistant powered by Azure AI Foundry. I can help with budget insights, spending patterns, and transaction analysis. What would you like to know?",
  sender: 'bot',
};

const Chat: React.FC = () => {
  const { user } = useAuthContext();
  const [messages, setMessages] = useState<Message[]>([WELCOME_MSG]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const listEndRef = useRef<HTMLDivElement>(null);

  // Load persisted chat history on mount
  useEffect(() => {
    if (!user?.id) return;
    const loadHistory = async () => {
      try {
        const res = await apiClient.get(`/chat/history/${user.id}`);
        const history: Message[] = (res.data.messages || []).map((m: { role: string; text: string }, i: number) => ({
          id: i + 1,
          text: m.text,
          sender: m.role === 'user' ? 'user' as const : 'bot' as const,
        }));
        if (history.length > 0) {
          setMessages([WELCOME_MSG, ...history]);
        }
      } catch {
        // No history available — keep welcome message
      }
    };
    loadHistory();
  }, [user?.id]);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    listEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = async () => {
    if (!input.trim()) return;

    const userMessage: Message = {
      id: Date.now(),
      text: input,
      sender: 'user',
    };
    
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setLoading(true);

    try {
      const response = await apiClient.post('/chat', {
        user_id: user?.id || 'anonymous',
        message: input,
        context: {}
      });

      const botResponse: Message = {
        id: Date.now() + 1,
        text: response.data.response,
        sender: 'bot',
      };
      setMessages(prev => [...prev, botResponse]);
    } catch (error) {
      const botResponse: Message = {
        id: Date.now() + 1,
        text: "Unable to connect to the AI assistant. Please ensure the chatbot service is running and Azure AI Foundry is configured.",
        sender: 'bot',
      };
      setMessages(prev => [...prev, botResponse]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        AI Financial Assistant
      </Typography>
      
      <Paper sx={{ p: 2, mb: 2, height: 400, overflow: 'auto' }}>
        <List>
          {messages.map((msg) => (
            <ListItem key={msg.id}>
              <ListItemText 
                primary={msg.text}
                secondary={msg.sender === 'user' ? 'You' : 'Assistant'}
                sx={{
                  bgcolor: msg.sender === 'user' ? 'primary.light' : 'grey.100',
                  borderRadius: 1,
                  p: 1,
                }}
              />
            </ListItem>
          ))}
          <div ref={listEndRef} />
        </List>
      </Paper>

      <Box sx={{ display: 'flex', gap: 1 }}>
        <TextField
          fullWidth
          placeholder="Ask about your finances..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !loading && handleSend()}
          disabled={loading}
        />
        <Button 
          variant="contained" 
          endIcon={loading ? <CircularProgress size={20} /> : <SendIcon />} 
          onClick={handleSend}
          disabled={loading || !input.trim()}
        >
          {loading ? 'Thinking...' : 'Send'}
        </Button>
      </Box>
    </Box>
  );
};

export default Chat;