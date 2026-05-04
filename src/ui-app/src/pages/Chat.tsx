import React, { useState } from 'react';
import { Box, Typography, Paper, TextField, Button, List, ListItem, ListItemText, Divider } from '@mui/material';
import SendIcon from '@mui/icons-material/Send';

interface Message {
  id: number;
  text: string;
  sender: 'user' | 'bot';
}

const Chat: React.FC = () => {
  const [messages, setMessages] = useState<Message[]>([
    { id: 1, text: 'Hello! I\'m your AI financial assistant. How can I help you today?', sender: 'bot' },
  ]);
  const [input, setInput] = useState('');

  const handleSend = () => {
    if (!input.trim()) return;

    const userMessage: Message = {
      id: Date.now(),
      text: input,
      sender: 'user',
    };
    
    setMessages([...messages, userMessage]);
    setInput('');

    // Simulate AI response
    setTimeout(() => {
      const botResponse: Message = {
        id: Date.now() + 1,
        text: getBotResponse(input),
        sender: 'bot',
      };
      setMessages(prev => [...prev, botResponse]);
    }, 1000);
  };

  const getBotResponse = (question: string): string => {
    const lower = question.toLowerCase();
    if (lower.includes('balance')) return 'Your total balance across all accounts is $18,963.12. Checking: $2,543.78, Savings: $15,234.56, Credit: -$876.23';
    if (lower.includes('transfer')) return 'I can help you make a transfer. Would you like to move money between your checking and savings accounts?';
    if (lower.includes('spending')) return 'This month you\'ve spent $1,234.56. Your top categories are: Groceries ($345), Dining ($210), and Gas ($180).';
    return 'I can help with balance inquiries, transfers, spending analysis, and budget recommendations. What would you like to know?';
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
          onKeyPress={(e) => e.key === 'Enter' && handleSend()}
        />
        <Button variant="contained" endIcon={<SendIcon />} onClick={handleSend}>
          Send
        </Button>
      </Box>
    </Box>
  );
};

export default Chat;