import React from 'react';

const useNavigate = () => jest.fn();
const useLocation = () => ({ pathname: '/', search: '', hash: '', state: null });
const useParams = () => ({});

export {
  useNavigate,
  useLocation,
  useParams,
};
