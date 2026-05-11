import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import DocumentUpload, { UploadedDocument } from '../../components/account-opening/DocumentUpload';

describe('DocumentUpload', () => {
  const mockUpload = jest.fn();
  const mockDelete = jest.fn();
  const applicationId = 'app-123';

  const mockPhotoIdFile = new File(['photo-id'], 'drivers-license.jpg', { type: 'image/jpeg' });
  const mockProofOfAddressFile = new File(['proof'], 'utility-bill.pdf', { type: 'application/pdf' });
  const mockLargeFile = new File(['x'.repeat(15 * 1024 * 1024)], 'large.jpg', { type: 'image/jpeg' });
  const mockInvalidFile = new File(['text'], 'document.txt', { type: 'text/plain' });

  const mockUploadedDoc: UploadedDocument = {
    id: 'doc-123',
    type: 'photo_id',
    fileName: 'drivers-license.jpg',
    fileSize: 102400,
    blobUrl: 'https://example.com/doc-123',
    uploadedAt: '2026-05-11T10:00:00Z',
  };

  beforeEach(() => {
    mockUpload.mockClear();
    mockDelete.mockClear();
  });

  describe('Happy Path', () => {
    it('renders upload areas for both document types', () => {
      render(<DocumentUpload applicationId={applicationId} onUpload={mockUpload} />);

      expect(screen.getByText(/photo id/i)).toBeInTheDocument();
      expect(screen.getByText(/proof of address/i)).toBeInTheDocument();
      expect(screen.getAllByText(/drag and drop your file here/i)).toHaveLength(2);
    });

    it('uploads photo ID successfully via file input', async () => {
      const user = userEvent.setup();
      mockUpload.mockResolvedValue({
        id: 'doc-123',
        type: 'photo_id',
        fileName: mockPhotoIdFile.name,
        fileSize: mockPhotoIdFile.size,
        blobUrl: 'https://example.com/doc-123',
        uploadedAt: new Date().toISOString(),
      });

      render(<DocumentUpload applicationId={applicationId} onUpload={mockUpload} />);

      const photoIdInput = screen.getByTestId('photo_id-input');
      await user.upload(photoIdInput, mockPhotoIdFile);

      await waitFor(() => {
        expect(mockUpload).toHaveBeenCalledWith(mockPhotoIdFile, 'photo_id');
      });

      expect(await screen.findByText(/uploaded: drivers-license.jpg/i)).toBeInTheDocument();
    });

    it('uploads proof of address successfully', async () => {
      const user = userEvent.setup();
      mockUpload.mockResolvedValue({
        id: 'doc-456',
        type: 'proof_of_address',
        fileName: mockProofOfAddressFile.name,
        fileSize: mockProofOfAddressFile.size,
        blobUrl: 'https://example.com/doc-456',
        uploadedAt: new Date().toISOString(),
      });

      render(<DocumentUpload applicationId={applicationId} onUpload={mockUpload} />);

      const proofInput = screen.getByTestId('proof_of_address-input');
      await user.upload(proofInput, mockProofOfAddressFile);

      await waitFor(() => {
        expect(mockUpload).toHaveBeenCalledWith(mockProofOfAddressFile, 'proof_of_address');
      });

      expect(await screen.findByText(/uploaded: utility-bill.pdf/i)).toBeInTheDocument();
    });

    it('displays existing documents', () => {
      const existingDocs: UploadedDocument[] = [mockUploadedDoc];

      render(
        <DocumentUpload
          applicationId={applicationId}
          onUpload={mockUpload}
          existingDocuments={existingDocs}
        />
      );

      expect(screen.getByText(/uploaded: drivers-license.jpg/i)).toBeInTheDocument();
      expect(screen.getByText(/photo_id/i)).toBeInTheDocument();
    });

    it('shows uploaded documents list', async () => {
      const user = userEvent.setup();
      mockUpload.mockResolvedValue(mockUploadedDoc);

      render(<DocumentUpload applicationId={applicationId} onUpload={mockUpload} />);

      const photoIdInput = screen.getByTestId('photo_id-input');
      await user.upload(photoIdInput, mockPhotoIdFile);

      await waitFor(() => {
        expect(screen.getByText('Uploaded Documents')).toBeInTheDocument();
      });

      expect(screen.getByText(/drivers-license.jpg/i)).toBeInTheDocument();
    });
  });

  describe('Drag and Drop', () => {
    it('handles drag and drop file upload', async () => {
      mockUpload.mockResolvedValue(mockUploadedDoc);

      render(<DocumentUpload applicationId={applicationId} onUpload={mockUpload} />);

      const uploadAreas = screen.getAllByText(/drag and drop your file here/i);
      const photoIdArea = uploadAreas[0].closest('[class*="MuiPaper"]');

      if (photoIdArea) {
        const dropEvent = new Event('drop', { bubbles: true });
        Object.defineProperty(dropEvent, 'dataTransfer', {
          value: {
            files: [mockPhotoIdFile],
          },
        });

        fireEvent.drop(photoIdArea, dropEvent);

        await waitFor(() => {
          expect(mockUpload).toHaveBeenCalledWith(mockPhotoIdFile, 'photo_id');
        });
      }
    });

    it('highlights upload area on drag over', () => {
      render(<DocumentUpload applicationId={applicationId} onUpload={mockUpload} />);

      const uploadAreas = screen.getAllByText(/drag and drop your file here/i);
      const photoIdArea = uploadAreas[0].closest('[class*="MuiPaper"]');

      if (photoIdArea) {
        fireEvent.dragOver(photoIdArea);
        // Visual feedback would be tested via style changes
      }
    });

    it('removes highlight on drag leave', () => {
      render(<DocumentUpload applicationId={applicationId} onUpload={mockUpload} />);

      const uploadAreas = screen.getAllByText(/drag and drop your file here/i);
      const photoIdArea = uploadAreas[0].closest('[class*="MuiPaper"]');

      if (photoIdArea) {
        fireEvent.dragOver(photoIdArea);
        fireEvent.dragLeave(photoIdArea);
        // Visual feedback would be tested via style changes
      }
    });
  });

  describe('Validation', () => {
    it('shows error for invalid file type', async () => {
      const user = userEvent.setup();

      render(<DocumentUpload applicationId={applicationId} onUpload={mockUpload} />);

      const photoIdInput = screen.getByTestId('photo_id-input');
      await user.upload(photoIdInput, mockInvalidFile);

      expect(await screen.findByText(/invalid file type/i)).toBeInTheDocument();
      expect(mockUpload).not.toHaveBeenCalled();
    });

    it('shows error for file too large', async () => {
      const user = userEvent.setup();

      render(<DocumentUpload applicationId={applicationId} onUpload={mockUpload} />);

      const photoIdInput = screen.getByTestId('photo_id-input');
      await user.upload(photoIdInput, mockLargeFile);

      expect(await screen.findByText(/file too large/i)).toBeInTheDocument();
      expect(mockUpload).not.toHaveBeenCalled();
    });

    it('accepts custom max file size', async () => {
      const user = userEvent.setup();
      const smallMaxSize = 1024; // 1KB

      render(
        <DocumentUpload
          applicationId={applicationId}
          onUpload={mockUpload}
          maxFileSize={smallMaxSize}
        />
      );

      const photoIdInput = screen.getByTestId('photo_id-input');
      await user.upload(photoIdInput, mockPhotoIdFile);

      expect(await screen.findByText(/file too large/i)).toBeInTheDocument();
    });

    it('accepts custom file formats', async () => {
      const user = userEvent.setup();
      const customFormats = ['application/pdf'];

      render(
        <DocumentUpload
          applicationId={applicationId}
          onUpload={mockUpload}
          acceptedFormats={customFormats}
        />
      );

      const photoIdInput = screen.getByTestId('photo_id-input');
      await user.upload(photoIdInput, mockPhotoIdFile);

      expect(await screen.findByText(/invalid file type/i)).toBeInTheDocument();
      expect(mockUpload).not.toHaveBeenCalled();
    });
  });

  describe('Error Handling', () => {
    it('displays error when upload fails', async () => {
      const user = userEvent.setup();
      const errorMessage = 'Network error';
      mockUpload.mockRejectedValue(new Error(errorMessage));

      render(<DocumentUpload applicationId={applicationId} onUpload={mockUpload} />);

      const photoIdInput = screen.getByTestId('photo_id-input');
      await user.upload(photoIdInput, mockPhotoIdFile);

      expect(await screen.findByText(errorMessage)).toBeInTheDocument();
    });

    it('shows loading indicator during upload', async () => {
      const user = userEvent.setup();
      mockUpload.mockImplementation(
        () => new Promise((resolve) => setTimeout(() => resolve(mockUploadedDoc), 1000))
      );

      render(<DocumentUpload applicationId={applicationId} onUpload={mockUpload} />);

      const photoIdInput = screen.getByTestId('photo_id-input');
      await user.upload(photoIdInput, mockPhotoIdFile);

      expect(screen.getByRole('progressbar')).toBeInTheDocument();

      await waitFor(() => {
        expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
      });
    });

    it('clears error when uploading new file', async () => {
      const user = userEvent.setup();
      mockUpload.mockRejectedValueOnce(new Error('Upload failed'));

      render(<DocumentUpload applicationId={applicationId} onUpload={mockUpload} />);

      const photoIdInput = screen.getByTestId('photo_id-input');
      await user.upload(photoIdInput, mockInvalidFile);

      expect(await screen.findByText(/invalid file type/i)).toBeInTheDocument();

      mockUpload.mockResolvedValue(mockUploadedDoc);
      await user.upload(photoIdInput, mockPhotoIdFile);

      await waitFor(() => {
        expect(screen.queryByText(/invalid file type/i)).not.toBeInTheDocument();
      });
    });
  });

  describe('Delete Functionality', () => {
    it('deletes document when delete button is clicked', async () => {
      const user = userEvent.setup();
      mockDelete.mockResolvedValue(undefined);

      const existingDocs: UploadedDocument[] = [mockUploadedDoc];

      render(
        <DocumentUpload
          applicationId={applicationId}
          onUpload={mockUpload}
          onDelete={mockDelete}
          existingDocuments={existingDocs}
        />
      );

      const deleteButtons = screen.getAllByRole('button');
      const deleteButton = deleteButtons.find((btn) => 
        btn.querySelector('[data-testid="DeleteIcon"]')
      );

      if (deleteButton) {
        await user.click(deleteButton);

        await waitFor(() => {
          expect(mockDelete).toHaveBeenCalledWith('doc-123');
        });

        await waitFor(() => {
          expect(screen.queryByText(/uploaded: drivers-license.jpg/i)).not.toBeInTheDocument();
        });
      }
    });

    it('does not show delete button when onDelete is not provided', () => {
      const existingDocs: UploadedDocument[] = [mockUploadedDoc];

      render(
        <DocumentUpload
          applicationId={applicationId}
          onUpload={mockUpload}
          existingDocuments={existingDocs}
        />
      );

      const deleteButtons = screen.queryAllByRole('button').filter((btn) => 
        btn.querySelector('[data-testid="DeleteIcon"]')
      );

      expect(deleteButtons).toHaveLength(0);
    });
  });

  describe('Replace Functionality', () => {
    it('allows replacing an uploaded document', async () => {
      const user = userEvent.setup();
      mockUpload.mockResolvedValue(mockUploadedDoc);

      const existingDocs: UploadedDocument[] = [mockUploadedDoc];

      render(
        <DocumentUpload
          applicationId={applicationId}
          onUpload={mockUpload}
          existingDocuments={existingDocs}
        />
      );

      const replaceButton = screen.getByRole('button', { name: /replace/i });
      expect(replaceButton).toBeInTheDocument();
    });

    it('replaces document when new file is uploaded for same type', async () => {
      const user = userEvent.setup();
      const newDoc = { ...mockUploadedDoc, id: 'doc-new', fileName: 'new-id.jpg' };
      mockUpload.mockResolvedValue(newDoc);

      render(
        <DocumentUpload
          applicationId={applicationId}
          onUpload={mockUpload}
          existingDocuments={[mockUploadedDoc]}
        />
      );

      const photoIdInput = screen.getByTestId('photo_id-input');
      const newFile = new File(['new'], 'new-id.jpg', { type: 'image/jpeg' });
      await user.upload(photoIdInput, newFile);

      await waitFor(() => {
        expect(screen.getByText(/uploaded: new-id.jpg/i)).toBeInTheDocument();
      });

      expect(screen.queryByText(/uploaded: drivers-license.jpg/i)).not.toBeInTheDocument();
    });
  });

  describe('Edge Cases', () => {
    it('handles multiple uploads to different document types', async () => {
      const user = userEvent.setup();
      mockUpload.mockResolvedValueOnce({
        id: 'doc-photo',
        type: 'photo_id',
        fileName: mockPhotoIdFile.name,
        fileSize: mockPhotoIdFile.size,
      } as UploadedDocument);

      mockUpload.mockResolvedValueOnce({
        id: 'doc-proof',
        type: 'proof_of_address',
        fileName: mockProofOfAddressFile.name,
        fileSize: mockProofOfAddressFile.size,
      } as UploadedDocument);

      render(<DocumentUpload applicationId={applicationId} onUpload={mockUpload} />);

      const photoIdInput = screen.getByTestId('photo_id-input');
      await user.upload(photoIdInput, mockPhotoIdFile);

      await waitFor(() => {
        expect(screen.getByText(/uploaded: drivers-license.jpg/i)).toBeInTheDocument();
      });

      const proofInput = screen.getByTestId('proof_of_address-input');
      await user.upload(proofInput, mockProofOfAddressFile);

      await waitFor(() => {
        expect(screen.getByText(/uploaded: utility-bill.pdf/i)).toBeInTheDocument();
      });

      expect(screen.getAllByText(/uploaded:/i)).toHaveLength(2);
    });

    it('displays file size in KB correctly', () => {
      const doc = { ...mockUploadedDoc, fileSize: 1536 }; // 1.5 KB
      render(
        <DocumentUpload
          applicationId={applicationId}
          onUpload={mockUpload}
          existingDocuments={[doc]}
        />
      );

      expect(screen.getByText(/1\.50 kb/i)).toBeInTheDocument();
    });

    it('handles upload with missing file in event', async () => {
      const user = userEvent.setup();
      render(<DocumentUpload applicationId={applicationId} onUpload={mockUpload} />);

      const photoIdInput = screen.getByTestId('photo_id-input');
      
      // Simulate file input change with no file
      fireEvent.change(photoIdInput, { target: { files: [] } });

      await waitFor(() => {
        expect(mockUpload).not.toHaveBeenCalled();
      });
    });
  });
});
