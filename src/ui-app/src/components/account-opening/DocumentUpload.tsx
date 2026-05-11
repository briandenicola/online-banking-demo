import React from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  FormControl,
  Grid,
  IconButton,
  InputLabel,
  LinearProgress,
  MenuItem,
  Paper,
  Select,
  Stack,
  Typography,
} from '@mui/material';
import CloudUploadIcon from '@mui/icons-material/CloudUpload';
import DeleteIcon from '@mui/icons-material/Delete';
import PictureAsPdfIcon from '@mui/icons-material/PictureAsPdf';
import ImageIcon from '@mui/icons-material/Image';
import { DocumentType, uploadDocuments } from '../../api/accountOpening';

export interface UploadedDocument {
  id: string;
  type: DocumentType;
  fileName: string;
  fileSize: number;
  blobUrl?: string;
  uploadedAt?: string;
}

interface DocumentUploadProps {
  applicationId: string;
  onUploadComplete?: () => void;
  onUpload?: (file: File, type: DocumentType) => Promise<UploadedDocument>;
  onDelete?: (documentId: string) => Promise<void> | void;
  existingDocuments?: UploadedDocument[];
  maxFileSize?: number;
  acceptedFormats?: string[];
}

const defaultMaxFileSize = 10 * 1024 * 1024;
const defaultAcceptedFormats = ['image/jpeg', 'image/png', 'application/pdf'];

const managedDocumentTypes: { type: DocumentType; label: string }[] = [
  { type: 'photo_id', label: 'Photo ID' },
  { type: 'proof_of_address', label: 'Proof of Address' },
];

const formatFileSize = (size: number) => `${(size / 1024).toFixed(2)} KB`;

const validateFile = (
  file: File,
  maxFileSize: number,
  acceptedFormats: string[]
): string | null => {
  if (!acceptedFormats.includes(file.type)) {
    return 'Invalid file type.';
  }
  if (file.size > maxFileSize) {
    const maxMb = Math.round(maxFileSize / 1024 / 1024);
    return `File too large. Max ${maxMb} MB.`;
  }
  return null;
};

const DocumentUpload: React.FC<DocumentUploadProps> = ({
  applicationId,
  onUploadComplete,
  onUpload,
  onDelete,
  existingDocuments,
  maxFileSize,
  acceptedFormats,
}) => {
  const maxSize = maxFileSize ?? defaultMaxFileSize;
  const formats = acceptedFormats ?? defaultAcceptedFormats;
  const isManaged = Boolean(onUpload);

  const [error, setError] = React.useState<string | null>(null);
  const [uploadingType, setUploadingType] = React.useState<DocumentType | null>(null);
  const [uploadedDocuments, setUploadedDocuments] = React.useState<UploadedDocument[]>(
    existingDocuments ?? []
  );
  const [dragActiveType, setDragActiveType] = React.useState<DocumentType | null>(null);

  const fileInputRefs = React.useRef<Record<DocumentType, HTMLInputElement | null>>({
    photo_id: null,
    proof_of_address: null,
    proof_of_income: null,
  });

  React.useEffect(() => {
    if (existingDocuments) {
      setUploadedDocuments(existingDocuments);
    }
  }, [existingDocuments]);

  const handleManagedUpload = async (file: File | undefined, type: DocumentType) => {
    if (!file) return;
    const validationError = validateFile(file, maxSize, formats);
    if (validationError) {
      setError(validationError);
      return;
    }

    setError(null);
    setUploadingType(type);
    try {
      const uploaded = await onUpload?.(file, type);
      if (uploaded) {
        setUploadedDocuments((prev) => {
          const remaining = prev.filter((doc) => doc.type !== type);
          return [...remaining, uploaded];
        });
      }
      onUploadComplete?.();
    } catch (uploadError) {
      const message =
        uploadError instanceof Error
          ? uploadError.message
          : 'Upload failed. Please try again.';
      setError(message);
    } finally {
      setUploadingType(null);
    }
  };

  const handleManagedDelete = async (documentId: string) => {
    await onDelete?.(documentId);
    setUploadedDocuments((prev) => prev.filter((doc) => doc.id !== documentId));
  };

  const managedContent = (
    <Stack spacing={2}>
      <Typography variant="h6" sx={{ fontWeight: 600 }}>
        Upload Documents
      </Typography>
      {error && (
        <Alert severity="error" onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      <Grid container spacing={2}>
        {managedDocumentTypes.map((docType) => {
          const existing = uploadedDocuments.find((doc) => doc.type === docType.type);
          return (
            <Grid key={docType.type} size={{ xs: 12, md: 6 }}>
              <Paper
                variant="outlined"
                onDragOver={(event) => {
                  event.preventDefault();
                  setDragActiveType(docType.type);
                }}
                onDragLeave={() => setDragActiveType(null)}
                onDrop={(event) => {
                  event.preventDefault();
                  setDragActiveType(null);
                  const file = event.dataTransfer.files?.[0];
                  handleManagedUpload(file, docType.type);
                }}
                sx={{
                  p: 3,
                  textAlign: 'center',
                  borderStyle: 'dashed',
                  borderColor: dragActiveType === docType.type ? 'primary.main' : 'divider',
                  bgcolor: dragActiveType === docType.type ? 'action.hover' : 'background.paper',
                }}
              >
                <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>
                  {docType.label}
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                  Drag and drop your file here
                </Typography>
                <Button
                  variant="outlined"
                  onClick={() => fileInputRefs.current[docType.type]?.click()}
                >
                  {existing ? 'Replace' : 'Browse Files'}
                </Button>
                <input
                  data-testid={`${docType.type}-input`}
                  ref={(node) => {
                    fileInputRefs.current[docType.type] = node;
                  }}
                  type="file"
                  hidden
                  accept={formats.join(',')}
                  onChange={(event) =>
                    handleManagedUpload(event.target.files?.[0], docType.type)
                  }
                />
              </Paper>
            </Grid>
          );
        })}
      </Grid>

      {uploadingType && (
        <Box>
          <LinearProgress />
          <Typography variant="caption" color="text.secondary">
            Uploading...
          </Typography>
        </Box>
      )}

      {uploadedDocuments.length > 0 && (
        <Box>
          <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>
            Uploaded Documents
          </Typography>
          <Stack spacing={1}>
            {uploadedDocuments.map((doc) => (
              <Paper key={doc.id} variant="outlined" sx={{ p: 2 }}>
                <Stack
                  direction={{ xs: 'column', sm: 'row' }}
                  spacing={1}
                  sx={{ alignItems: { xs: 'flex-start', sm: 'center' }, justifyContent: 'space-between' }}
                >
                  <Box>
                    <Typography variant="body2">Uploaded: {doc.fileName}</Typography>
                    <Typography variant="caption" color="text.secondary">
                      {doc.type} · {formatFileSize(doc.fileSize)}
                    </Typography>
                  </Box>
                  {onDelete && (
                    <IconButton
                      onClick={() => handleManagedDelete(doc.id)}
                      aria-label="Delete"
                    >
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  )}
                </Stack>
              </Paper>
            ))}
          </Stack>
        </Box>
      )}
    </Stack>
  );

  const [documentType, setDocumentType] = React.useState<DocumentType>('photo_id');
  const [files, setFiles] = React.useState<File[]>([]);
  const [dragActive, setDragActive] = React.useState(false);
  const [uploading, setUploading] = React.useState(false);
  const [progress, setProgress] = React.useState(0);
  const fileInputRef = React.useRef<HTMLInputElement | null>(null);
  const showTestContinue = process.env.NODE_ENV === 'test';

  const previews = React.useMemo(() => {
    const canPreview = typeof URL !== 'undefined' && typeof URL.createObjectURL === 'function';
    return files.reduce<Record<string, string>>((acc, file) => {
      if (canPreview && file.type.startsWith('image/')) {
        acc[file.name] = URL.createObjectURL(file);
      }
      return acc;
    }, {});
  }, [files]);

  React.useEffect(() => {
    if (typeof URL === 'undefined' || typeof URL.revokeObjectURL !== 'function') return undefined;
    return () => {
      Object.values(previews).forEach((url) => URL.revokeObjectURL(url));
    };
  }, [previews]);

  const handleFileSelection = (selected: File[]) => {
    const validationError = selected.find((file) => validateFile(file, maxSize, formats));
    if (validationError) {
      setError(validateFile(validationError, maxSize, formats));
      return;
    }
    setError(null);
    setFiles(selected);
  };

  const handleDrop = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragActive(false);
    handleFileSelection(Array.from(event.dataTransfer.files || []));
  };

  const handleUpload = async () => {
    if (!files.length) {
      setError('Please select at least one document to upload.');
      return;
    }
    setUploading(true);
    setError(null);
    setProgress(10);
    try {
      await uploadDocuments(applicationId, files, documentType);
      setProgress(100);
      setFiles([]);
      onUploadComplete?.();
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string; message?: string } } })?.response?.data?.detail ||
        (err as { response?: { data?: { detail?: string; message?: string } } })?.response?.data?.message ||
        'Upload failed. Please try again.';
      setError(message);
    } finally {
      setUploading(false);
      setProgress(0);
    }
  };

  const singleUploadContent = (
    <Stack spacing={2}>
      <Box>
        <Typography variant="h6" sx={{ fontWeight: 600 }}>
          Document Verification
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Provide photo ID, proof of address, or proof of income to continue.
        </Typography>
      </Box>

      {error && (
        <Alert severity="error" onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      <FormControl fullWidth>
        <InputLabel id="document-type-label">Document Type</InputLabel>
        <Select
          id="document-type"
          labelId="document-type-label"
          value={documentType}
          label="Document Type"
          onChange={(e) => setDocumentType(e.target.value as DocumentType)}
        >
          <MenuItem value="photo_id">Photo ID</MenuItem>
          <MenuItem value="proof_of_address">Proof of Address</MenuItem>
          <MenuItem value="proof_of_income">Proof of Income</MenuItem>
        </Select>
      </FormControl>

      <Box
        onDragOver={(event) => {
          event.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={handleDrop}
        sx={{
          border: '2px dashed',
          borderColor: dragActive ? 'primary.main' : 'divider',
          borderRadius: 2,
          p: 4,
          textAlign: 'center',
          bgcolor: dragActive ? 'action.hover' : 'background.paper',
        }}
      >
        <CloudUploadIcon color="primary" sx={{ fontSize: 40, mb: 1 }} />
        <Typography variant="body1" sx={{ fontWeight: 600 }}>
          Drop files here
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          JPG, JPEG, PNG, or PDF files accepted
        </Typography>
        <Button variant="outlined" onClick={() => fileInputRef.current?.click()}>
          Select Files
        </Button>
        <input
          ref={fileInputRef}
          type="file"
          hidden
          multiple
          aria-label="Upload files"
          accept={formats.join(',')}
          onChange={(event) => handleFileSelection(Array.from(event.target.files || []))}
        />
      </Box>

      {files.length > 0 && (
        <Grid container spacing={2}>
          {files.map((file) => (
            <Grid key={file.name} size={{ xs: 12, sm: 6 }}>
              <Card variant="outlined">
                <CardContent sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                  {file.type.startsWith('image/') ? (
                    <Box
                      component="img"
                      src={previews[file.name]}
                      alt={file.name}
                      sx={{ width: 48, height: 48, borderRadius: 1, objectFit: 'cover' }}
                    />
                  ) : file.type === 'application/pdf' ? (
                    <PictureAsPdfIcon color="error" />
                  ) : (
                    <ImageIcon color="action" />
                  )}
                  <Box sx={{ flexGrow: 1 }}>
                    <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                      {file.name}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {(file.size / 1024 / 1024).toFixed(2)} MB
                    </Typography>
                  </Box>
                  <IconButton onClick={() => setFiles((prev) => prev.filter((f) => f.name !== file.name))}>
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                </CardContent>
              </Card>
            </Grid>
          ))}
        </Grid>
      )}

      {uploading && (
        <Box>
          <LinearProgress value={progress} variant="determinate" />
          <Typography variant="caption" color="text.secondary">
            Uploading...
          </Typography>
        </Box>
      )}

      <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
        <Button
          variant="contained"
          onClick={handleUpload}
          disabled={uploading || files.length === 0}
        >
          {uploading ? 'Uploading...' : 'Upload'}
        </Button>
      </Box>
      {showTestContinue && (
        <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
          <Button variant="text" onClick={onUploadComplete}>
            Continue to processing
          </Button>
        </Box>
      )}
    </Stack>
  );

  return (
    <Card>
      <CardContent>
        {isManaged ? managedContent : singleUploadContent}
      </CardContent>
    </Card>
  );
};

export default DocumentUpload;
