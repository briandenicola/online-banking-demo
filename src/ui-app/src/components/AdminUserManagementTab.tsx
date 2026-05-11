import React, { useState, useEffect, useCallback } from 'react';
import {
  Box,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  Chip,
  Button,
  IconButton,
  Tooltip,
  CircularProgress,
  Alert,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions,
  TextField,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import LockIcon from '@mui/icons-material/Lock';
import LockOpenIcon from '@mui/icons-material/LockOpen';
import KeyIcon from '@mui/icons-material/Key';
import DeleteIcon from '@mui/icons-material/Delete';
import apiClient from '../api/client';
import { useAuth } from '../context/AuthContext';

interface AdminUser {
  id: string;
  username: string;
  email: string;
  firstName: string;
  lastName: string;
  role: string;
  createdAt: string;
  lastLoginAt: string | null;
  isActive: boolean;
  isLocked: boolean;
}

const AdminUserManagementTab: React.FC = () => {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  // Reset password dialog
  const [resetDialogOpen, setResetDialogOpen] = useState(false);
  const [resetUserId, setResetUserId] = useState<string | null>(null);
  const [resetUsername, setResetUsername] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [passwordError, setPasswordError] = useState('');

  // Delete confirmation dialog
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deleteUserId, setDeleteUserId] = useState<string | null>(null);
  const [deleteUsername, setDeleteUsername] = useState('');

  const fetchUsers = useCallback(async () => {
    try {
      setError(null);
      const res = await apiClient.get('/admin/users');
      setUsers(res.data);
    } catch {
      setError('Failed to load users. Please try again.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  const handleLockToggle = async (id: string, isLocked: boolean) => {
    setActionLoading(id);
    try {
      const action = isLocked ? 'unlock' : 'lock';
      await apiClient.put(`/admin/users/${id}/${action}`);
      await fetchUsers();
    } catch {
      setError('Failed to update user lock status.');
    } finally {
      setActionLoading(null);
    }
  };

  const openResetDialog = (id: string, username: string) => {
    setResetUserId(id);
    setResetUsername(username);
    setNewPassword('');
    setPasswordError('');
    setResetDialogOpen(true);
  };

  const handleResetPassword = async () => {
    if (newPassword.length < 8) {
      setPasswordError('Password must be at least 8 characters');
      return;
    }
    if (!resetUserId) return;
    setActionLoading(resetUserId);
    setResetDialogOpen(false);
    try {
      await apiClient.put(`/admin/users/${resetUserId}/reset-password`, { newPassword });
      setError(null);
    } catch {
      setError('Failed to reset password.');
    } finally {
      setActionLoading(null);
    }
  };

  const openDeleteDialog = (id: string, username: string) => {
    setDeleteUserId(id);
    setDeleteUsername(username);
    setDeleteDialogOpen(true);
  };

  const handleDelete = async () => {
    if (!deleteUserId) return;
    setActionLoading(deleteUserId);
    setDeleteDialogOpen(false);
    try {
      await apiClient.delete(`/admin/users/${deleteUserId}`);
      await fetchUsers();
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { message?: string } } })?.response?.data?.message ||
        'Failed to delete user.';
      setError(msg);
    } finally {
      setActionLoading(null);
    }
  };

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return '—';
    return new Date(dateStr).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box>
      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 2 }}>
        <Button startIcon={<RefreshIcon />} onClick={fetchUsers} variant="outlined" size="small">
          Refresh
        </Button>
      </Box>

      <TableContainer component={Paper} elevation={2}>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell>Username</TableCell>
              <TableCell>Email</TableCell>
              <TableCell>Name</TableCell>
              <TableCell>Role</TableCell>
              <TableCell>Created</TableCell>
              <TableCell>Last Login</TableCell>
              <TableCell>Status</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {users.length === 0 ? (
              <TableRow>
                <TableCell colSpan={8} align="center">
                  No users found
                </TableCell>
              </TableRow>
            ) : (
              users.map((u) => {
                const isSelf = currentUser?.id === u.id;
                return (
                  <TableRow key={u.id}>
                    <TableCell>{u.username}</TableCell>
                    <TableCell>{u.email}</TableCell>
                    <TableCell>
                      {u.firstName} {u.lastName}
                    </TableCell>
                    <TableCell>
                      <Chip
                        label={u.role}
                        color={u.role === 'admin' ? 'primary' : 'default'}
                        size="small"
                      />
                    </TableCell>
                    <TableCell>{formatDate(u.createdAt)}</TableCell>
                    <TableCell>{formatDate(u.lastLoginAt)}</TableCell>
                    <TableCell>
                      {u.isLocked ? (
                        <Chip label="Locked" color="error" size="small" />
                      ) : u.isActive ? (
                        <Chip label="Active" color="success" size="small" />
                      ) : (
                        <Chip label="Inactive" size="small" />
                      )}
                    </TableCell>
                    <TableCell align="right">
                      <Tooltip title={u.isLocked ? 'Unlock' : 'Lock'}>
                        <span>
                          <IconButton
                            size="small"
                            onClick={() => handleLockToggle(u.id, u.isLocked)}
                            disabled={actionLoading === u.id || isSelf}
                          >
                            {actionLoading === u.id ? (
                              <CircularProgress size={18} />
                            ) : u.isLocked ? (
                              <LockOpenIcon fontSize="small" />
                            ) : (
                              <LockIcon fontSize="small" />
                            )}
                          </IconButton>
                        </span>
                      </Tooltip>
                      <Tooltip title="Reset Password">
                        <span>
                          <IconButton
                            size="small"
                            onClick={() => openResetDialog(u.id, u.username)}
                            disabled={actionLoading === u.id}
                          >
                            <KeyIcon fontSize="small" />
                          </IconButton>
                        </span>
                      </Tooltip>
                      <Tooltip title={isSelf ? 'Cannot delete yourself' : 'Delete User'}>
                        <span>
                          <IconButton
                            size="small"
                            color="error"
                            onClick={() => openDeleteDialog(u.id, u.username)}
                            disabled={actionLoading === u.id || isSelf}
                          >
                            <DeleteIcon fontSize="small" />
                          </IconButton>
                        </span>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Reset Password Dialog */}
      <Dialog open={resetDialogOpen} onClose={() => setResetDialogOpen(false)}>
        <DialogTitle>Reset Password</DialogTitle>
        <DialogContent>
          <DialogContentText sx={{ mb: 2 }}>
            Enter a new password for <strong>{resetUsername}</strong>.
          </DialogContentText>
          <TextField
            autoFocus
            fullWidth
            type="password"
            label="New Password"
            value={newPassword}
            onChange={(e) => {
              setNewPassword(e.target.value);
              setPasswordError('');
            }}
            error={!!passwordError}
            helperText={passwordError || 'Minimum 8 characters'}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setResetDialogOpen(false)}>Cancel</Button>
          <Button onClick={handleResetPassword} variant="contained" disabled={!newPassword}>
            Reset
          </Button>
        </DialogActions>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog open={deleteDialogOpen} onClose={() => setDeleteDialogOpen(false)}>
        <DialogTitle>Delete User</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Are you sure you want to delete <strong>{deleteUsername}</strong>? This action cannot be
            undone.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteDialogOpen(false)}>Cancel</Button>
          <Button onClick={handleDelete} variant="contained" color="error">
            Delete
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default AdminUserManagementTab;
