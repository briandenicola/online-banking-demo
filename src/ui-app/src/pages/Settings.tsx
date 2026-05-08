import React, { useState, useEffect, useRef } from 'react';
import {
  Box,
  Typography,
  Paper,
  TextField,
  Button,
  Avatar,
  IconButton,
  Chip,
  Alert,
  Snackbar,
  Divider,
  List,
  ListItem,
  ListItemText,
  ListItemSecondaryAction,
  CircularProgress,
} from '@mui/material';
import PhotoCameraIcon from '@mui/icons-material/PhotoCamera';
import DeleteIcon from '@mui/icons-material/Delete';
import EditIcon from '@mui/icons-material/Edit';
import AddIcon from '@mui/icons-material/Add';
import SaveIcon from '@mui/icons-material/Save';
import LockResetIcon from '@mui/icons-material/LockReset';
import CategoryIcon from '@mui/icons-material/Category';
import CheckIcon from '@mui/icons-material/Check';
import CloseIcon from '@mui/icons-material/Close';
import apiClient from '../api/client';
import { useAuthContext } from '../contexts/AuthContext';

const Settings: React.FC = () => {
  const { user } = useAuthContext();

  // Password state
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [passwordLoading, setPasswordLoading] = useState(false);

  // Avatar state
  const [avatarSrc, setAvatarSrc] = useState<string | null>(null);
  const [avatarLoading, setAvatarLoading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Categories state
  const [categories, setCategories] = useState<string[]>([]);
  const [newCategory, setNewCategory] = useState('');
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [editingValue, setEditingValue] = useState('');
  const [categoriesLoading, setCategoriesLoading] = useState(false);
  const [categoriesDirty, setCategoriesDirty] = useState(false);

  // Snackbar
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: 'success' | 'error' }>({
    open: false,
    message: '',
    severity: 'success',
  });

  const showMessage = (message: string, severity: 'success' | 'error' = 'success') => {
    setSnackbar({ open: true, message, severity });
  };

  // Load avatar and categories on mount
  useEffect(() => {
    loadAvatar();
    loadCategories();
  }, []);

  const loadAvatar = async () => {
    try {
      const res = await apiClient.get('/users/me/avatar');
      if (res.data.avatar) {
        setAvatarSrc(res.data.avatar);
      }
    } catch {
      // No avatar set
    }
  };

  const loadCategories = async () => {
    try {
      const res = await apiClient.get('/users/me/categories');
      setCategories(res.data.categories || []);
    } catch {
      // No categories
    }
  };

  // Password change
  const handlePasswordChange = async () => {
    if (newPassword !== confirmPassword) {
      showMessage('New passwords do not match', 'error');
      return;
    }
    if (newPassword.length < 6) {
      showMessage('New password must be at least 6 characters', 'error');
      return;
    }
    setPasswordLoading(true);
    try {
      await apiClient.put('/users/me/password', {
        currentPassword,
        newPassword,
      });
      showMessage('Password changed successfully');
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
    } catch (err: unknown) {
      const message = (err as { response?: { data?: { message?: string } } })?.response?.data?.message || 'Failed to change password';
      showMessage(message, 'error');
    } finally {
      setPasswordLoading(false);
    }
  };

  // Avatar upload
  const handleAvatarSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    if (file.size > 500_000) {
      showMessage('Image too large. Max 500KB.', 'error');
      return;
    }

    const reader = new FileReader();
    reader.onload = async (e) => {
      const base64 = e.target?.result as string;
      setAvatarLoading(true);
      try {
        await apiClient.put('/users/me/avatar', { avatarBase64: base64 });
        setAvatarSrc(base64);
        showMessage('Avatar updated');
      } catch {
        showMessage('Failed to upload avatar', 'error');
      } finally {
        setAvatarLoading(false);
      }
    };
    reader.readAsDataURL(file);
  };

  // Category CRUD
  const handleAddCategory = () => {
    const trimmed = newCategory.trim();
    if (!trimmed) return;
    if (categories.includes(trimmed)) {
      showMessage('Category already exists', 'error');
      return;
    }
    setCategories([...categories, trimmed]);
    setNewCategory('');
    setCategoriesDirty(true);
  };

  const handleDeleteCategory = (index: number) => {
    setCategories(categories.filter((_, i) => i !== index));
    setCategoriesDirty(true);
  };

  const handleStartEdit = (index: number) => {
    setEditingIndex(index);
    setEditingValue(categories[index]);
  };

  const handleSaveEdit = () => {
    if (editingIndex === null) return;
    const trimmed = editingValue.trim();
    if (!trimmed) return;
    const updated = [...categories];
    updated[editingIndex] = trimmed;
    setCategories(updated);
    setEditingIndex(null);
    setEditingValue('');
    setCategoriesDirty(true);
  };

  const handleCancelEdit = () => {
    setEditingIndex(null);
    setEditingValue('');
  };

  const handleSaveCategories = async () => {
    setCategoriesLoading(true);
    try {
      const res = await apiClient.put('/users/me/categories', { categories });
      setCategories(res.data.categories || categories);
      setCategoriesDirty(false);
      showMessage('Category preferences saved — AI will use these as hints');
    } catch {
      showMessage('Failed to save categories', 'error');
    } finally {
      setCategoriesLoading(false);
    }
  };

  const initials = user
    ? `${(user.firstName?.[0] || '').toUpperCase()}${(user.lastName?.[0] || '').toUpperCase()}`
    : '?';

  return (
    <Box>
      <Typography variant="h4" sx={{ fontWeight: 700, mb: 1 }}>
        Settings
      </Typography>
      <Typography variant="body1" color="text.secondary" sx={{ mb: 3 }}>
        Manage your profile, security, and transaction preferences
      </Typography>

      {/* Profile / Avatar Section */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <Typography variant="h6" sx={{ mb: 2, display: 'flex', alignItems: 'center', gap: 1 }}>
          <PhotoCameraIcon /> Profile
        </Typography>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 3 }}>
          <Box sx={{ position: 'relative' }}>
            <Avatar
              src={avatarSrc || undefined}
              sx={{ width: 80, height: 80, fontSize: '1.8rem', bgcolor: 'primary.main' }}
            >
              {!avatarSrc && initials}
            </Avatar>
            <IconButton
              size="small"
              sx={{
                position: 'absolute',
                bottom: -4,
                right: -4,
                bgcolor: 'background.paper',
                border: '2px solid',
                borderColor: 'divider',
                '&:hover': { bgcolor: 'action.hover' },
              }}
              onClick={() => fileInputRef.current?.click()}
              disabled={avatarLoading}
            >
              {avatarLoading ? <CircularProgress size={16} /> : <PhotoCameraIcon fontSize="small" />}
            </IconButton>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg,image/gif"
              style={{ display: 'none' }}
              onChange={handleAvatarSelect}
            />
          </Box>
          <Box>
            <Typography variant="h6">
              {user?.firstName} {user?.lastName}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {user?.email}
            </Typography>
            <Chip label={user?.role || 'user'} size="small" color={user?.role === 'admin' ? 'warning' : 'default'} sx={{ mt: 0.5 }} />
          </Box>
        </Box>
      </Paper>

      {/* Password Change Section */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <Typography variant="h6" sx={{ mb: 2, display: 'flex', alignItems: 'center', gap: 1 }}>
          <LockResetIcon /> Change Password
        </Typography>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, maxWidth: 400 }}>
          <TextField
            label="Current Password"
            type="password"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            size="small"
            fullWidth
          />
          <TextField
            label="New Password"
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            size="small"
            fullWidth
          />
          <TextField
            label="Confirm New Password"
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            size="small"
            fullWidth
            error={confirmPassword.length > 0 && newPassword !== confirmPassword}
            helperText={confirmPassword.length > 0 && newPassword !== confirmPassword ? 'Passwords do not match' : ''}
          />
          <Button
            variant="contained"
            startIcon={passwordLoading ? <CircularProgress size={16} /> : <LockResetIcon />}
            onClick={handlePasswordChange}
            disabled={passwordLoading || !currentPassword || !newPassword || !confirmPassword}
            sx={{ alignSelf: 'flex-start' }}
          >
            Change Password
          </Button>
        </Box>
      </Paper>

      {/* Transaction Categories Section */}
      <Paper sx={{ p: 3 }}>
        <Typography variant="h6" sx={{ mb: 0.5, display: 'flex', alignItems: 'center', gap: 1 }}>
          <CategoryIcon /> Transaction Categories
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Define custom categories. The AI will use these as hints when categorizing your transactions.
        </Typography>

        {/* Add new category */}
        <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
          <TextField
            label="New category"
            value={newCategory}
            onChange={(e) => setNewCategory(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleAddCategory()}
            size="small"
            sx={{ flexGrow: 1, maxWidth: 400 }}
          />
          <Button
            variant="outlined"
            startIcon={<AddIcon />}
            onClick={handleAddCategory}
            disabled={!newCategory.trim()}
          >
            Add
          </Button>
        </Box>

        <Divider sx={{ mb: 1 }} />

        {categories.length === 0 ? (
          <Typography variant="body2" color="text.secondary" sx={{ py: 2, textAlign: 'center' }}>
            No custom categories yet. Add some to help the AI categorize your transactions.
          </Typography>
        ) : (
          <List dense>
            {categories.map((cat, index) => (
              <ListItem key={index} divider>
                {editingIndex === index ? (
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%' }}>
                    <TextField
                      value={editingValue}
                      onChange={(e) => setEditingValue(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') handleSaveEdit();
                        if (e.key === 'Escape') handleCancelEdit();
                      }}
                      size="small"
                      autoFocus
                      sx={{ flexGrow: 1 }}
                    />
                    <IconButton size="small" onClick={handleSaveEdit} color="success">
                      <CheckIcon fontSize="small" />
                    </IconButton>
                    <IconButton size="small" onClick={handleCancelEdit}>
                      <CloseIcon fontSize="small" />
                    </IconButton>
                  </Box>
                ) : (
                  <>
                    <ListItemText primary={cat} />
                    <ListItemSecondaryAction>
                      <IconButton size="small" onClick={() => handleStartEdit(index)}>
                        <EditIcon fontSize="small" />
                      </IconButton>
                      <IconButton size="small" onClick={() => handleDeleteCategory(index)} color="error">
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </ListItemSecondaryAction>
                  </>
                )}
              </ListItem>
            ))}
          </List>
        )}

        {categoriesDirty && (
          <Box sx={{ mt: 2 }}>
            <Alert severity="info" sx={{ mb: 1 }}>
              You have unsaved changes to your categories.
            </Alert>
            <Button
              variant="contained"
              startIcon={categoriesLoading ? <CircularProgress size={16} /> : <SaveIcon />}
              onClick={handleSaveCategories}
              disabled={categoriesLoading}
            >
              Save Categories
            </Button>
          </Box>
        )}
      </Paper>

      <Snackbar
        open={snackbar.open}
        autoHideDuration={4000}
        onClose={() => setSnackbar({ ...snackbar, open: false })}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert severity={snackbar.severity} onClose={() => setSnackbar({ ...snackbar, open: false })}>
          {snackbar.message}
        </Alert>
      </Snackbar>
    </Box>
  );
};

export default Settings;
