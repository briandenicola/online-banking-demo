FROM mcr.microsoft.com/dotnet/sdk:10.0-alpine AS build
WORKDIR /src

# Copy central package management
COPY Directory.Packages.props ./

# Copy shared projects
COPY src/shared/Contracts/*.csproj ./shared/Contracts/
COPY src/shared/Observability/*.csproj ./shared/Observability/

# Copy loan-origination-service project
COPY src/loan-origination-service/*.csproj ./loan-origination-service/
RUN dotnet restore "./loan-origination-service/LoanOrigination.csproj"

# Copy everything else
COPY src/shared/Contracts/. ./shared/Contracts/
COPY src/shared/Observability/. ./shared/Observability/
COPY src/loan-origination-service/. ./loan-origination-service/

WORKDIR /src/loan-origination-service
RUN dotnet publish -c Release -o /app/publish

FROM mcr.microsoft.com/dotnet/aspnet:10.0-alpine AS runtime
WORKDIR /app
COPY --from=build /app/publish .
USER $APP_UID
ENTRYPOINT ["dotnet", "LoanOrigination.dll"]
