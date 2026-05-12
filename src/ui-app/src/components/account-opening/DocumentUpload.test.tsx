import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import DocumentUpload from './DocumentUpload';

jest.mock('../../api/accountOpening', () => ({
  uploadDocuments: jest.fn(),
}));

jest.mock('../../api/client', () => ({
  __esModule: true,
  default: {
    post: jest.fn(),
    get: jest.fn(),
    interceptors: {
      request: { use: jest.fn() },
      response: { use: jest.fn() },
    },
  },
}));

import { uploadDocuments } from '../../api/accountOpening';

const mockUploadDocuments = uploadDocuments as jest.MockedFunction<typeof uploadDocuments>;

const renderUpload = (props = {}) => {
  return render(
    <DocumentUpload
      applicationId="app-1"
      onUploadComplete={jest.fn()}
      {...props}
    />
  );
};

// Helper to create a mock File
const createMockFile = (
  name: string,
  sizeInBytes: number,
  type: string
): File => {
  const content = new Array(sizeInBytes).fill('a').join('');
  return new File([content], name, { type });
};

describe('DocumentUpload', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Rendering', () => {
    test('renders upload drop zone', () => {
      renderUpload();

      expect(
        screen.getByText(/drag.*drop|upload|browse/i)
      ).toBeInTheDocument();
    });

    test('renders document type selector', () => {
      renderUpload();

      // Should have options for photo ID and proof of address at minimum
      expect(
        screen.getByLabelText(/Document Type/i) ||
        screen.getByRole('combobox') ||
        screen.getByText(/Photo ID|Proof of Address/i)
      ).toBeTruthy();
    });

    test('shows accepted file types hint', () => {
      renderUpload();

      expect(
        screen.getByText(/jpg|jpeg|png|pdf/i)
      ).toBeInTheDocument();
    });
  });

  describe('File validation', () => {
    test('accepts valid JPG file', async () => {
      renderUpload();

      const file = createMockFile('photo-id.jpg', 1024, 'image/jpeg');
      const input = screen.getByLabelText(/upload|file/i) || document.querySelector('input[type="file"]');

      if (input) {
        fireEvent.change(input, { target: { files: [file] } });

        await waitFor(() => {
          expect(screen.getByText(/photo-id\.jpg/i)).toBeInTheDocument();
        });
      }
    });

    test('accepts valid PNG file', async () => {
      renderUpload();

      const file = createMockFile('id-scan.png', 2048, 'image/png');
      const input = screen.getByLabelText(/upload|file/i) || document.querySelector('input[type="file"]');

      if (input) {
        fireEvent.change(input, { target: { files: [file] } });

        await waitFor(() => {
          expect(screen.getByText(/id-scan\.png/i)).toBeInTheDocument();
        });
      }
    });

    test('accepts valid PDF file', async () => {
      renderUpload();

      const file = createMockFile('utility-bill.pdf', 4096, 'application/pdf');
      const input = screen.getByLabelText(/upload|file/i) || document.querySelector('input[type="file"]');

      if (input) {
        fireEvent.change(input, { target: { files: [file] } });

        await waitFor(() => {
          expect(screen.getByText(/utility-bill\.pdf/i)).toBeInTheDocument();
        });
      }
    });

    test('rejects files over 10MB', async () => {
      renderUpload();

      const oversizedFile = createMockFile('huge-scan.jpg', 11 * 1024 * 1024, 'image/jpeg');
      const input = screen.getByLabelText(/upload|file/i) || document.querySelector('input[type="file"]');

      if (input) {
        fireEvent.change(input, { target: { files: [oversizedFile] } });

        await waitFor(() => {
          expect(
            screen.getByText(/too large|exceeds|10\s*MB|size limit/i)
          ).toBeInTheDocument();
        });
      }
    });
  });

  describe('File preview', () => {
    test('shows file preview after selection', async () => {
      renderUpload();

      const file = createMockFile('photo-id.jpg', 1024, 'image/jpeg');
      const input = screen.getByLabelText(/upload|file/i) || document.querySelector('input[type="file"]');

      if (input) {
        fireEvent.change(input, { target: { files: [file] } });

        await waitFor(() => {
          // Should show filename or preview element
          expect(screen.getByText(/photo-id\.jpg/i)).toBeInTheDocument();
        });
      }
    });
  });

  describe('Upload API integration', () => {
    test('calls uploadDocuments API on upload action', async () => {
      const onUploadComplete = jest.fn();
      mockUploadDocuments.mockResolvedValueOnce({ documentIds: ['doc-1'] });

      render(
        <DocumentUpload
          applicationId="app-1"
          onUploadComplete={onUploadComplete}
        />
      );

      const file = createMockFile('photo-id.jpg', 1024, 'image/jpeg');
      const input = screen.getByLabelText(/upload|file/i) || document.querySelector('input[type="file"]');

      if (input) {
        fireEvent.change(input, { target: { files: [file] } });

        // Find and click the upload/submit button
        await waitFor(() => {
          const uploadButton = screen.getByRole('button', { name: /upload|submit/i });
          fireEvent.click(uploadButton);
        });

        await waitFor(() => {
          expect(mockUploadDocuments).toHaveBeenCalledWith(
            'app-1',
            expect.any(Array),
            expect.any(String)
          );
        });
      }
    });

    test('calls onUploadComplete after successful upload', async () => {
      const onUploadComplete = jest.fn();
      mockUploadDocuments.mockResolvedValueOnce({ documentIds: ['doc-1'] });

      render(
        <DocumentUpload
          applicationId="app-1"
          onUploadComplete={onUploadComplete}
        />
      );

      const file = createMockFile('photo-id.jpg', 1024, 'image/jpeg');
      const input = screen.getByLabelText(/upload|file/i) || document.querySelector('input[type="file"]');

      if (input) {
        fireEvent.change(input, { target: { files: [file] } });

        await waitFor(() => {
          const uploadButton = screen.getByRole('button', { name: /upload|submit/i });
          fireEvent.click(uploadButton);
        });

        await waitFor(() => {
          expect(onUploadComplete).toHaveBeenCalled();
        });
      }
    });

    test('shows progress indicator during upload', async () => {
      // Create a promise we control to simulate slow upload
      let resolveUpload: (value: any) => void;
      const uploadPromise = new Promise((resolve) => {
        resolveUpload = resolve;
      });
      mockUploadDocuments.mockReturnValueOnce(uploadPromise as any);

      renderUpload();

      const file = createMockFile('photo-id.jpg', 1024, 'image/jpeg');
      const input = screen.getByLabelText(/upload|file/i) || document.querySelector('input[type="file"]');

      if (input) {
        fireEvent.change(input, { target: { files: [file] } });

        await waitFor(() => {
          const uploadButton = screen.getByRole('button', { name: /upload|submit/i });
          fireEvent.click(uploadButton);
        });

        // During upload, should show a progress indicator
        await waitFor(() => {
          expect(
            screen.getByRole('progressbar') ||
            screen.getByText(/uploading|progress/i)
          ).toBeTruthy();
        });

        // Complete the upload
        resolveUpload!({ documentIds: ['doc-1'] });
      }
    });

    test('shows error on upload failure', async () => {
      mockUploadDocuments.mockRejectedValueOnce({
        response: { status: 500, data: { detail: 'Upload failed' } },
      });

      renderUpload();

      const file = createMockFile('photo-id.jpg', 1024, 'image/jpeg');
      const input = screen.getByLabelText(/upload|file/i) || document.querySelector('input[type="file"]');

      if (input) {
        fireEvent.change(input, { target: { files: [file] } });

        await waitFor(() => {
          const uploadButton = screen.getByRole('button', { name: /upload|submit/i });
          fireEvent.click(uploadButton);
        });

        await waitFor(() => {
          expect(
            screen.getByText(/error|failed|try again/i)
          ).toBeInTheDocument();
        });
      }
    });
  });
});
