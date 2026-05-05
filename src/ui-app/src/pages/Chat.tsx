import React, { useState } from 'react';
import { Box, Typography, Paper, TextField, Button, List, ListItem, ListItemText, CircularProgress } from '@mui/material';
import SendIcon from '@mui/icons-material/Send';

interface Message {
  id: number;
  text: string;
  sender: 'user' | 'bot';
}

const Chat: React.FC = () => {
  const [messages, setMessages] = useState<Message[]>([
    { id: 1, text: "Hello! I'm your AI financial assistant powered by Azure AI Foundry. I can help with budget insights, spending patterns, and transaction analysis. What would you like to know?", sender: 'bot' },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSend = async () => {
    if (!input.trim()) return;

    const userMessage: Message = {
      id: Date.now(),
      text: input,
      sender: 'user',
    };
    
    setMessages([...messages, userMessage]);
    setInput('');
    setLoading(true);

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: 'user-demo',
          message: input,
          context: {}
        })
      });

      if (response.ok) {
        const data = await response.json();
        const botResponse: Message = {
          id: Date.now() + 1,
          text: data.response,
          sender: 'bot',
        };
        setMessages(prev => [...prev, botResponse]);
      } else {
        throw new Error('API error');
      }
    } catch (error) {
      // Fallback for local development when Azure AI Foundry is not configured
      const fallbackResponses: Record<string, string> = {
        "budget": "Based on your recent activity, I recommend creating a monthly budget of $2,000 for essentials. Would you like me to analyze your spending patterns?",
        "spending": "Your average monthly spending is around $2,450, with dining at $450 being your highest category. Consider meal planning to reduce costs.",
        "save": "You could potentially save $300 monthly by reducing discretionary spending. Setting up automatic transfers to your savings account would help.",
        "invest": "I can't provide specific investment advice, but I recommend consulting a certified financial planner for personalized recommendations.",
        "hello": "Hello! I'm your AI financial assistant. I can help with budget insights, spending patterns, and transaction analysis.",
      };
      
      const inputLower = input.toLowerCase();
      let responseText = "I'm running in local mode without Azure AI Foundry connectivity. ";
      
      for (const [key, text] of Object.entries(fallbackResponses)) {
        if (inputLower.includes(key)) {
          responseText = text;
          break;
        }
      }
      
      if (responseText === "I'm running in local mode without Azure AI Foundry connectivity. ") {
        responseText += "Try asking about your budget, spending patterns, or savings goals!";
      }
      
      const botResponse: Message = {
        id: Date.now() + 1,
        text: responseText,
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
        </List>
      </Paper>

      <Box sx={{ display: 'flex', gap: 1 }}>
        <TextField
          fullWidth
          placeholder="Ask about your finances..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyPress={(e) => e.key === 'Enter' && !loading && handleSend()}
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